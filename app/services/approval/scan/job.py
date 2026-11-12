"""Minute scan entry. The orchestrator runs the six steps."""


def run_scan() -> None:
    from app.services.approval.scan.orchestrator import ScanOrchestrator

    ScanOrchestrator().execute()
