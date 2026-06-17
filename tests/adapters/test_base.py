"""测试 adapter 契约：缺方法的子类不能实例化、registry 能识别合法子类。"""

from __future__ import annotations

import pytest

from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob, discover_adapters


def test_subclass_missing_methods_cannot_instantiate() -> None:
    class Broken(CampusAdapter):
        company = "broken"

    with pytest.raises(TypeError):
        Broken()  # type: ignore[abstract]


def test_minimal_concrete_subclass_instantiates() -> None:
    class Toy(CampusAdapter):
        company = "toy"

        def list_jobs(self, fetcher):  # type: ignore[override]
            yield RawJob(source_url="https://example.com/1", payload={"id": 1})

        def normalize(self, raw):  # type: ignore[override]
            return NormalizedJob(
                job_id=f"toy:{raw.payload['id']}",
                company="toy",
                title="后端开发",
                description="",
                requirements="",
                location=[],
                education=None,
                job_type="校招",
                department=None,
                posted_at=None,
                source_url=raw.source_url,
                raw_payload=raw.payload,
            )

    a = Toy()
    assert a.company == "toy"
    assert a.rate_limit_qps == 1.0

    b = Toy(rate_limit_qps=0.5)
    assert b.rate_limit_qps == 0.5

    raws = list(a.list_jobs(fetcher=None))  # type: ignore[arg-type]
    assert len(raws) == 1
    n = a.normalize(raws[0])
    assert n.job_id == "toy:1"
    assert n.company == "toy"


def test_discover_adapters_returns_real_company_adapters() -> None:
    found = discover_adapters()
    assert isinstance(found, dict)
    for name, cls in found.items():
        assert issubclass(cls, CampusAdapter)
        assert cls.company == name
