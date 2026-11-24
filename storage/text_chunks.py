"""通用文本共享存储；制度条款索引仍由原有业务维护。"""
import json
import math

from core.config import app_config
from .adapters import storage

TEXT_TABLE = "pdf_text_chunks"


def validate_chunks(chunks):
    """拒绝不完整或混合批次，避免用半成品替换原文件。"""
    if not chunks:
        raise ValueError("文本块不能为空")
    dim = len(chunks[0].embedding or [])
    seen = set()
    for chunk in chunks:
        vector = chunk.embedding or []
        if (not chunk.file_id or chunk.file_id != chunks[0].file_id
                or not chunk.chunk_id or chunk.chunk_id in seen
                or not dim or len(vector) != dim
                or not all(math.isfinite(v) for v in vector)
                or not any(vector)):
            raise ValueError("文件、分块 ID 或文本向量无效，未写入数据库")
        seen.add(chunk.chunk_id)
    return dim


class TextChunkStore:
    def __init__(self, adapter=None):
        self.adapter = adapter if adapter is not None else storage.relational

    def _check_model(self, cur, dim):
        cur.execute("SELECT model, dimension FROM pdf_text_settings WHERE singleton = TRUE")
        row = cur.fetchone()
        if row != (app_config.embedding.model_name, dim):
            raise ValueError("共享文本表的嵌入模型或维度不匹配，请使用原模型或建立新版本存储")

    def ensure(self, cur, dim):
        """在调用者事务中创建结构；模型登记与建表一起提交。"""
        if not 1 <= dim <= 2000:
            raise ValueError("共享文本 HNSW 索引支持 1 至 2000 维向量")
        # 已初始化后只读模型登记，避免所有文件写入被结构锁串行化。
        cur.execute("SELECT to_regclass(format('%I.%I', current_schema(), 'pdf_text_chunks'))")
        if cur.fetchone()[0] is not None:
            self._check_model(cur, dim)
            return
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('pdf_text_schema'))")
        cur.execute("""CREATE TABLE IF NOT EXISTS pdf_text_settings (
            singleton BOOLEAN PRIMARY KEY CHECK (singleton), model TEXT NOT NULL,
            dimension INTEGER NOT NULL)""")
        cur.execute("""INSERT INTO pdf_text_settings VALUES (TRUE, %s, %s)
            ON CONFLICT DO NOTHING""", (app_config.embedding.model_name, dim))
        self._check_model(cur, dim)
        cur.execute(f"""CREATE TABLE IF NOT EXISTS {TEXT_TABLE} (
            id BIGSERIAL UNIQUE, file_id TEXT NOT NULL, chunk_id TEXT NOT NULL,
            embedding vector({dim}) NOT NULL, metadata JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(), PRIMARY KEY(file_id, chunk_id))""")
        cur.execute(f"""CREATE INDEX IF NOT EXISTS pdf_text_chunks_embedding_hnsw
            ON {TEXT_TABLE} USING hnsw (embedding vector_cosine_ops)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS pdf_text_imports (
            file_id TEXT PRIMARY KEY, source_name TEXT NOT NULL,
            source_count BIGINT NOT NULL, imported_count BIGINT NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW())""")

    @staticmethod
    def lock_file(cur, file_id):
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('pdf_text_file'), hashtext(%s))", (file_id,))

    @staticmethod
    def mark(cur, file_id, source, source_count, imported_count):
        cur.execute("""INSERT INTO pdf_text_imports (file_id, source_name, source_count, imported_count)
            VALUES (%s, %s, %s, %s) ON CONFLICT (file_id) DO UPDATE SET
            source_name=EXCLUDED.source_name, source_count=EXCLUDED.source_count,
            imported_count=EXCLUDED.imported_count, updated_at=NOW()""",
                    (file_id, source, source_count, imported_count))

    def replace(self, chunks, *, update_provenance=False, expected_file=None):
        dim = validate_chunks(chunks)
        file_id = chunks[0].file_id
        from psycopg2.extras import execute_batch
        with self.adapter.transaction(), self.adapter.conn.cursor() as cur:
            if expected_file is not None:
                # 与重置保持“文件行、文件锁”的相同顺序，防止死锁及清理后旧重建写回。
                cur.execute("SELECT file_hash,status,embedding_model,updated_at FROM pdf_files WHERE file_id=%s FOR UPDATE", (file_id,))
                current=cur.fetchone()
                expected=tuple(expected_file.get(key) for key in ('file_hash','status','embedding_model','updated_at'))
                if current is None or tuple(current)!=expected:
                    raise ValueError('文件在重建期间已被重置、重新处理或修改，未替换文本，请核实后重试')
            self.lock_file(cur, file_id)
            self.ensure(cur, dim)
            cur.execute(f"DELETE FROM {TEXT_TABLE} WHERE file_id=%s", (file_id,))
            rows = [(file_id, c.chunk_id, json.dumps(c.embedding), json.dumps({
                "file_id": file_id, "chunk_id": c.chunk_id, "block_id": c.block_id,
                "page_num": c.page_num, "text": c.text}, ensure_ascii=False)) for c in chunks]
            execute_batch(cur, f"INSERT INTO {TEXT_TABLE} (file_id,chunk_id,embedding,metadata) "
                          "VALUES (%s,%s,%s::vector,%s::jsonb)", rows)
            self.mark(cur, file_id, "native", len(rows), len(rows))
            if update_provenance:
                # 定向重建与溯源更新共用事务，任一步失败都保留原共享表数据。
                cur.execute("SELECT to_regclass(format('%I.%I', current_schema(), 'pdf_block_storage'))")
                if cur.fetchone()[0]:
                    cur.execute("""UPDATE pdf_block_storage SET storage_location=%s
                        WHERE file_id=%s AND storage_target='pg_vector'""", (TEXT_TABLE,file_id))
        return len(chunks)

    def search(self, vector, top_k=10, file_id=None):
        """指定文件先物化过滤结果，保证不走全库近似召回后过滤。"""
        if top_k < 1:
            raise ValueError("top_k 必须大于等于 1")
        import psycopg2.extras
        with self.adapter.conn.cursor() as cur:
            cur.execute("SELECT to_regclass(format('%I.%I', current_schema(), 'pdf_text_chunks'))")
            if cur.fetchone()[0] is None:
                return []
            self._check_model(cur, len(vector))
        prefix = ""
        params = []
        source = TEXT_TABLE
        if file_id:
            prefix = f"WITH filtered AS MATERIALIZED (SELECT * FROM {TEXT_TABLE} WHERE file_id = %s) "
            params.append(file_id)
            source = "filtered"
        vec = json.dumps(vector)
        params.extend([vec, vec, top_k])
        with self.adapter.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(prefix + f"SELECT id, metadata, 1-(embedding <=> %s::vector) AS similarity "
                        f"FROM {source} ORDER BY embedding <=> %s::vector LIMIT %s", params)
            return [dict(row) for row in cur.fetchall()]
