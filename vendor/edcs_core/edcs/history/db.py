from __future__ import annotations

from sqlalchemy import (Column, DateTime, ForeignKey, Integer, String, Text,
                        create_engine)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class ScanJobRow(Base):
    __tablename__ = "scan_jobs"
    job_id = Column(String(32), primary_key=True)
    jira_id = Column(String(32), index=True)
    repo_url = Column(Text)
    message_id = Column(String(256), unique=True)
    requester = Column(String(256))
    received_at = Column(DateTime)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    doc_status = Column(String(8))
    code_status = Column(String(8))
    overall_status = Column(String(8))
    compliance_score = Column(Integer)
    stats_json = Column(Text)


class FindingRow(Base):
    __tablename__ = "findings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(32), ForeignKey("scan_jobs.job_id"), index=True)
    severity = Column(String(10))
    category = Column(String(32))
    file = Column(Text)
    line = Column(Integer, nullable=True)
    rule_id = Column(String(32))
    masked_text = Column(Text)
    reason = Column(Text)
    recommendation = Column(Text)


def make_session(db_url: str):
    engine = create_engine(db_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)
