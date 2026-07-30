"""Fail-closed detection pipeline and deterministic static checks."""

import re
from collections.abc import Sequence
from typing import Protocol

from agentloom.contracts import (
    DetectionReport,
    DetectionResult,
    DetectionStageName,
    Finding,
)


class DetectionStage(Protocol):
    stage: DetectionStageName

    async def inspect(self, subject: str) -> DetectionResult: ...


class StaticSkillScanner:
    stage: DetectionStageName = "STATIC"
    version = "0.1.0"

    _rules = (
        (
            "STATIC_PIPE_TO_SHELL",
            re.compile(r"(?i)\b(?:curl|wget)\b[^\n|]*\|\s*(?:sh|bash)\b"),
            "HIGH",
            "remote content is piped directly to a shell",
        ),
        (
            "STATIC_SENSITIVE_PATH",
            re.compile(r"(?i)(?:~[/\\]\.ssh|\.ssh[/\\](?:id_rsa|id_ed25519))"),
            "HIGH",
            "skill references a sensitive SSH path",
        ),
    )

    async def inspect(self, subject: str) -> DetectionResult:
        findings = [
            Finding(rule_id=rule_id, severity=severity, message=message)
            for rule_id, pattern, severity, message in self._rules
            if pattern.search(subject)
        ]
        return DetectionResult(
            stage=self.stage,
            verdict="UNSAFE" if findings else "PASSED",
            findings=findings,
            evidence_refs=[],
            detector_versions={"static-skill-scanner": self.version},
        )


class DetectionPipeline:
    def __init__(self, stages: Sequence[DetectionStage]) -> None:
        if not stages:
            raise ValueError("detection pipeline requires at least one stage")
        self._stages = stages

    async def run(self, subject: str) -> DetectionReport:
        results: list[DetectionResult] = []
        for stage in self._stages:
            try:
                result = await stage.inspect(subject)
            except Exception as exc:
                result = DetectionResult(
                    stage=stage.stage,
                    verdict="UNCERTAIN",
                    findings=[
                        Finding(
                            rule_id="DETECTOR_FAILURE",
                            severity="HIGH",
                            message=f"{stage.stage} detector failed: {exc}",
                        )
                    ],
                    evidence_refs=[],
                    detector_versions={stage.stage.lower(): "unknown"},
                )
            results.append(result)
            if result.verdict != "PASSED":
                return self._report(result.verdict, results)
        return self._report("PASSED", results)

    @staticmethod
    def _report(verdict: str, results: list[DetectionResult]) -> DetectionReport:
        return DetectionReport.model_validate(
            {
                "verdict": verdict,
                "results": results,
                "evidence_refs": [
                    evidence_ref
                    for result in results
                    for evidence_ref in result.evidence_refs
                ],
            }
        )
