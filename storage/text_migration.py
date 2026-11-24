"""将逐文件旧向量表迁移到共享表，不加载模型、不删除源表。"""
import re

from core.config import app_config
from .text_chunks import TextChunkStore, TEXT_TABLE


def inspect_source(cur, table, file_id, legacy_model):
    """全量检查来源身份、维度及重复 ID；未知模型须由操作者明确声明。"""
    cur.execute("SELECT to_regclass(format('%I.%I', current_schema(), 'pdf_files'))")
    model = None
    if cur.fetchone()[0]:
        cur.execute("SELECT embedding_model FROM pdf_files WHERE file_id=%s", (file_id,))
        row = cur.fetchone()
        model = row[0] if row else None
    model = model or legacy_model
    if not model:
        raise ValueError(f"{table}: 缺少模型记录；确认后使用 --legacy-embedding-model 声明旧模型")
    if model != app_config.embedding.model_name:
        raise ValueError(f"{table}: 旧模型 {model} 与当前配置不一致")
    cur.execute(f"""SELECT count(*), min(vector_dims(embedding)), max(vector_dims(embedding)),
        count(*) FILTER (WHERE embedding IS NULL OR vector_norm(embedding)=0
        OR metadata->>'file_id' IS DISTINCT FROM %s
        OR coalesce(metadata->>'chunk_id','')='' OR coalesce(metadata->>'text','')='')
        FROM "{table}"
        """, (file_id,))
    count, low, high, invalid = cur.fetchone()
    if invalid or (count and (low != high or not 1 <= low <= 2000)):
        raise ValueError(f"{table}: 文件标识、文本、向量或维度无效")
    cur.execute(f"""SELECT metadata->>'chunk_id' FROM "{table}"
        GROUP BY metadata->>'chunk_id' HAVING count(DISTINCT metadata)>1
        OR count(DISTINCT embedding::text)>1 LIMIT 1""")
    if cur.fetchone():
        raise ValueError(f"{table}: 同一 chunk_id 的内容或向量冲突，需人工处理")
    return count, low


def migrate_text_chunks(*, dry_run=False, legacy_model=None, adapter=None):
    """逐文件事务提交；失败不登记完成，可再次运行继续。"""
    store = TextChunkStore(adapter)
    db = store.adapter
    report = {"dry_run": dry_run, "files": [], "errors": []}
    expected_dim = None
    with db.conn.cursor() as cur:
        cur.execute("""SELECT tablename FROM pg_tables WHERE schemaname=current_schema()
            AND tablename ~ '^pdf_[A-Za-z0-9_]+_text$' ORDER BY tablename""")
        tables = [row[0] for row in cur.fetchall()]
    for table in tables:
        if not re.fullmatch(r"pdf_[A-Za-z0-9_]+_text", table):
            continue
        file_id = table[4:-5]
        try:
            with db.transaction(), db.conn.cursor() as cur:
                # 共享表写入者和迁移互斥；旧进程必须先停止。
                store.lock_file(cur, file_id)
                cur.execute(f'LOCK TABLE "{table}" IN SHARE MODE')
                cur.execute("SELECT to_regclass(format('%I.%I', current_schema(), 'pdf_text_imports'))")
                if cur.fetchone()[0]:
                    cur.execute("SELECT source_name FROM pdf_text_imports WHERE file_id=%s", (file_id,))
                    if cur.fetchone():
                        report["files"].append({"file_id": file_id, "status": "skipped"})
                        continue
                count, dim = inspect_source(cur, table, file_id, legacy_model)
                if not count:
                    report["files"].append({"file_id": file_id, "status": "empty", "rows": 0})
                    continue
                if expected_dim is not None and expected_dim != dim:
                    raise ValueError("各文件向量维度不一致，不能迁入同一共享表")
                if dry_run:
                    cur.execute("SELECT to_regclass(format('%I.%I', current_schema(), 'pdf_text_settings'))")
                    if cur.fetchone()[0]:
                        store._check_model(cur, dim)
                    cur.execute("SELECT to_regclass(format('%I.%I', current_schema(), 'pdf_text_chunks'))")
                    if cur.fetchone()[0]:
                        cur.execute(f"SELECT count(*) FROM {TEXT_TABLE} WHERE file_id=%s", (file_id,))
                        if cur.fetchone()[0]:
                            raise ValueError("共享表已有该文件但缺少迁移记录，停止以避免覆盖")
                    expected_dim = dim
                    report["files"].append({"file_id": file_id, "status": "ready", "rows": count})
                    continue
                store.ensure(cur, dim)
                cur.execute(f"SELECT count(*) FROM {TEXT_TABLE} WHERE file_id=%s", (file_id,))
                if cur.fetchone()[0]:
                    raise ValueError("共享表已有该文件但缺少迁移记录，停止以避免覆盖")
                cur.execute(f"""INSERT INTO {TEXT_TABLE} (file_id,chunk_id,embedding,metadata,created_at)
                    SELECT DISTINCT ON (metadata->>'chunk_id') %s, metadata->>'chunk_id',
                    embedding, metadata, created_at FROM "{table}"
                    ORDER BY metadata->>'chunk_id', id""", (file_id,))
                inserted = cur.rowcount
                # 逐条双向核对内容与向量，而不只比较数量。
                cur.execute(f"""SELECT count(*) FROM (
                    (SELECT metadata->>'chunk_id', embedding::text, metadata FROM "{table}"
                     EXCEPT SELECT chunk_id, embedding::text, metadata FROM {TEXT_TABLE} WHERE file_id=%s)
                    UNION ALL
                    (SELECT chunk_id, embedding::text, metadata FROM {TEXT_TABLE} WHERE file_id=%s
                     EXCEPT SELECT metadata->>'chunk_id', embedding::text, metadata FROM "{table}")
                    ) differences""", (file_id, file_id))
                if cur.fetchone()[0]:
                    raise ValueError("迁移内容校验失败，已回滚该文件")
                cur.execute("SELECT to_regclass(format('%I.%I', current_schema(), 'pdf_block_storage'))")
                if cur.fetchone()[0]:
                    cur.execute("""UPDATE pdf_block_storage SET storage_location=%s
                        WHERE file_id=%s AND storage_target='pg_vector' AND storage_location=%s""",
                                (TEXT_TABLE, file_id, table))
                store.mark(cur, file_id, table, count, inserted)
            expected_dim = dim
            report["files"].append({"file_id": file_id, "status": "migrated", "source_rows": count,
                                    "rows": inserted, "duplicates_removed": count-inserted})
        except Exception as exc:
            report["errors"].append({"file_id": file_id, "error": str(exc)})
    return report
