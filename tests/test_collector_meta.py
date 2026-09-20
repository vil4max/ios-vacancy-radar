from __future__ import annotations

from collector.types import CollectResult, SourceResult


def test_source_result_shape() -> None:
    result = CollectResult(
        source_results=[
            SourceResult(
                source_id="company:epam",
                source_name="EPAM",
                source_url="https://careers.epam.com/",
                jobs=[],
                status="healthy",
                error=None,
                response_ms=10,
            )
        ]
    )
    assert len(result.source_results) == 1
    assert result.source_results[0].source_name == "EPAM"
    assert result.source_results[0].status == "healthy"
