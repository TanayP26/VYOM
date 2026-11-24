from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db import KnowledgeDocument
from app.knowledge import retrieve, upsert


def test_current_policy_evidence_precedes_historical_documents():
    engine = create_engine("sqlite:///:memory:")
    KnowledgeDocument.__table__.create(engine)
    with Session(engine) as db:
        upsert(db, "docs/M1.md", "temporal-first recall historical development " * 20)
        upsert(db, "docs/MILESTONE1_3_1_B1_EVALUATION.md", "Current evaluation: 0/1 matched.")
        upsert(db, "docs/MILESTONE1_3_1_OPERATOR_POLICY.md", "Current operator policy.")
        results = retrieve(db, "Explain temporal-first recall", limit=2)
        assert [r["source"] for r in results] == [
            "docs/MILESTONE1_3_1_B1_EVALUATION.md",
            "docs/MILESTONE1_3_1_OPERATOR_POLICY.md",
        ]
        assert retrieve(db, "historical development", limit=1)[0]["source"] == "docs/M1.md"
    engine.dispose()
