from __future__ import annotations

import argparse
import json
import math
import time
import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CandidateProfile, ResumeDocument
from app.services.talent_recommendation_retrieval import (
    CandidateResumeChoice,
    search_candidate_vectors,
)


@dataclass(frozen=True)
class BenchmarkConfig:
    candidate_count: int = 10_000
    embedding_dimension: int = 1_536
    warmup_runs: int = 3
    sample_runs: int = 20
    p95_limit_ms: float = 1_000

    def validate(self) -> None:
        if self.candidate_count != 10_000:
            raise ValueError("F27 固定基准必须生成 10,000 名人才")
        if self.embedding_dimension < 8:
            raise ValueError("F27 固定基准的 Embedding 维度必须至少为 8")
        if self.warmup_runs < 3:
            raise ValueError("F27 固定基准至少预热 3 次")
        if self.sample_runs < 2:
            raise ValueError("F27 固定基准至少采样 2 次")


@dataclass(frozen=True)
class BenchmarkEmbeddingClient:
    model: str = "benchmark-embedding"
    version: str = "v1"
    dimension: int = 1_536
    batch_size: int = 100

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("数据库召回基准不允许调用外部 Embedding 服务")


def database_name_is_safe(database_url: str) -> bool:
    database = make_url(database_url).database or ""
    return database.endswith("_benchmark")


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        raise ValueError("无法计算空样本的百分位")
    if not 0 < ratio <= 1:
        raise ValueError("百分位比例必须在 0 到 1 之间")
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * ratio) - 1)
    return ordered[index]


def _assert_empty(db: Session) -> None:
    count = db.scalar(text("SELECT count(*) FROM resume_embedding_chunks"))
    if count:
        raise RuntimeError("F27 基准数据库必须是迁移完成后的空业务库")


def seed_benchmark_data(db: Session, config: BenchmarkConfig) -> None:
    config.validate()
    _assert_empty(db)
    parameters = {
        "candidate_count": config.candidate_count,
        "dimension": config.embedding_dimension,
        "tail_dimension": config.embedding_dimension - 8,
    }
    db.execute(
        text(
            """
            INSERT INTO resume_documents (
                id, original_filename, file_extension, content_type,
                detected_type, size_bytes, sha256, status, attempt_count
            )
            SELECT
                CAST(md5('talent-benchmark-document-' || value::text) AS uuid),
                'benchmark-' || value || '.pdf', '.pdf', 'application/pdf',
                'pdf', 100,
                md5('talent-benchmark-sha-' || value::text)
                    || md5('talent-benchmark-sha-2-' || value::text),
                'completed', 1
            FROM generate_series(1, :candidate_count) AS value
            """
        ),
        parameters,
    )
    db.execute(
        text(
            """
            INSERT INTO candidate_profiles (
                id, document_id, version_number, source, model_name,
                prompt_version, education, work_experiences, projects,
                skills, certifications, languages
            )
            SELECT
                CAST(md5('talent-benchmark-profile-' || value::text) AS uuid),
                CAST(md5('talent-benchmark-document-' || value::text) AS uuid),
                1, 'ai', 'benchmark-profile', 'benchmark-v1',
                '[]'::json, '[]'::json, '[]'::json,
                '[]'::json, '[]'::json, '[]'::json
            FROM generate_series(1, :candidate_count) AS value
            """
        ),
        parameters,
    )
    db.execute(
        text(
            """
            INSERT INTO resume_embedding_chunks (
                id, document_id, candidate_profile_id, profile_version,
                chunk_type, chunk_index, chunk_text, source_segment_keys,
                content_hash, embedding_model, embedding_dimension,
                embedding_version, embedding, status, attempt_count, embedded_at
            )
            SELECT
                CAST(md5('talent-benchmark-chunk-' || value::text) AS uuid),
                CAST(md5('talent-benchmark-document-' || value::text) AS uuid),
                CAST(md5('talent-benchmark-profile-' || value::text) AS uuid),
                1, 'summary', 0, 'F27 固定性能基准人才 ' || value,
                '["SEG-0001"]'::json,
                md5('talent-benchmark-content-' || value::text)
                    || md5('talent-benchmark-content-2-' || value::text),
                'benchmark-embedding', :dimension, 'v1',
                (
                    '[' || array_to_string(
                        ARRAY[
                            1.0,
                            ((value % 101) + 1)::double precision / 101.0,
                            ((value % 97) + 1)::double precision / 97.0,
                            ((value % 89) + 1)::double precision / 89.0,
                            ((value % 83) + 1)::double precision / 83.0,
                            ((value % 79) + 1)::double precision / 79.0,
                            ((value % 73) + 1)::double precision / 73.0,
                            ((value % 71) + 1)::double precision / 71.0
                        ] || array_fill(
                            0.0::double precision,
                            ARRAY[:tail_dimension]
                        ), ','
                    ) || ']'
                )::vector,
                'completed', 1, CURRENT_TIMESTAMP
            FROM generate_series(1, :candidate_count) AS value
            """
        ),
        parameters,
    )
    db.commit()


def _load_choices(
    db: Session,
    *,
    embedding_dimension: int,
) -> list[CandidateResumeChoice]:
    rows = db.execute(
        select(
            CandidateProfile.id,
            CandidateProfile.document_id,
            CandidateProfile.version_number,
            ResumeDocument.sha256,
            ResumeDocument.updated_at,
        ).join(ResumeDocument, ResumeDocument.id == CandidateProfile.document_id)
    ).all()
    return [
        CandidateResumeChoice(
            candidate_id=uuid.uuid5(uuid.NAMESPACE_URL, f"candidate:{profile_id}"),
            candidate_code=f"BENCH-{index:05d}",
            candidate_name=None,
            document_id=document_id,
            document_sha256=sha256 or "",
            document_updated_at=updated_at,
            profile_id=profile_id,
            profile_version=version_number,
            group_ids=(),
            embedding_model="benchmark-embedding",
            embedding_version="v1",
            embedding_dimension=embedding_dimension,
        )
        for index, (profile_id, document_id, version_number, sha256, updated_at) in enumerate(
            rows,
            start=1,
        )
    ]


def _timed_search(
    db: Session,
    choices: list[CandidateResumeChoice],
    client: BenchmarkEmbeddingClient,
) -> float:
    started = time.perf_counter()
    matches = search_candidate_vectors(
        db,
        choices=choices,
        query_vector=[1.0] + [0.0] * (client.dimension - 1),
        client=client,
        limit=50,
    )
    if len(matches) != 50:
        raise RuntimeError("F27 基准召回结果数量不是 50")
    return (time.perf_counter() - started) * 1_000


def run_benchmark(engine: Engine, config: BenchmarkConfig) -> dict[str, object]:
    config.validate()
    client = BenchmarkEmbeddingClient(dimension=config.embedding_dimension)
    with Session(engine) as db:
        choices = _load_choices(
            db,
            embedding_dimension=config.embedding_dimension,
        )
        if len(choices) != config.candidate_count:
            raise RuntimeError("F27 基准数据库人才数量不正确，请重新生成")
        for _ in range(config.warmup_runs):
            _timed_search(db, choices, client)
        samples = [
            _timed_search(db, choices, client) for _ in range(config.sample_runs)
        ]

    p95 = percentile(samples, 0.95)
    return {
        "config": asdict(config),
        "search_ms": {
            "p50": round(percentile(samples, 0.5), 2),
            "p95": round(p95, 2),
            "max": round(max(samples), 2),
        },
        "passed": p95 < config.p95_limit_ms,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="F27 人才向量召回固定规模性能基准")
    parser.add_argument("--seed", action="store_true", help="向空基准库生成固定数据")
    parser.add_argument("--warmup-runs", type=int, default=3)
    parser.add_argument("--sample-runs", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if settings.is_production or not database_name_is_safe(settings.database_url):
        raise RuntimeError("性能基准只允许在名称以 _benchmark 结尾的非生产数据库运行")
    config = BenchmarkConfig(
        warmup_runs=args.warmup_runs,
        sample_runs=args.sample_runs,
    )
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    if args.seed:
        with Session(engine) as db:
            seed_benchmark_data(db, config)
    result = run_benchmark(engine, config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
