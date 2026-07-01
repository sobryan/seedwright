"""The evaluator-optimizer authoring loop (spec §3A, FR-E.1, FR-H.7).

propose -> parse -> validate/compile -> sample -> judge -> (on pass) determinism gate -> finalize;
on any failure, feed the failures back and refine, up to ``max_iters``. Fail-fast preconditions
(capability floor, reference pools) run before/inside the loop so the model is never asked to fix
things it cannot. On exhaustion the loop RAISES with the full transcript — it never returns a
generator that failed the judge or the gate.
"""

from __future__ import annotations

from typing import Any

import seedwright_genlib
from seedwright_genlib.determinism import assert_deterministic
from seedwright_genlib.schema import SchemaSpec, TableClass

from .artifacts import GeneratorArtifacts, Provenance
from .capability import enforce_capability_floor
from .compile import GenSpecValidationError, compile_to_genlib
from .datatests import derive_data_tests, generate_sample, judge_sample
from .feedback import Failure
from .genspec import GenSpecParseError, parse_genspec
from .imported import ImportedSchema
from .provider import ProposeRequest, Provider
from .rules import RuleSet


class AuthoringFailed(RuntimeError):
    """The loop exhausted its iterations without a proposal that passed (FR-H.7)."""

    def __init__(self, transcript: list[dict[str, Any]], failures: tuple[Failure, ...]) -> None:
        self.transcript = transcript
        self.failures = failures
        super().__init__(f"authoring failed after {len(transcript)} iteration(s)")


class ReferencePoolMissing(RuntimeError):
    """A reference table has no key pool — un-actionable by the model, so the loop fails fast."""


def author(
    imported: ImportedSchema,
    rules: RuleSet,
    provider: Provider,
    *,
    max_iters: int = 4,
    sample_rows: int = 200,
    reference_pools: dict[str, Any] | None = None,
) -> GeneratorArtifacts:
    if max_iters < 1:
        raise ValueError("max_iters must be >= 1")
    enforce_capability_floor(provider.capabilities())

    transcript: list[dict[str, Any]] = []
    prior: dict[str, Any] | None = None
    failures: tuple[Failure, ...] = ()

    for iteration in range(1, max_iters + 1):
        response = provider.propose(ProposeRequest(imported, rules, prior, failures))
        prior = response.genspec

        try:
            genspec = parse_genspec(response.genspec)
            schema = compile_to_genlib(genspec, imported)
        except GenSpecParseError as exc:
            failures = (Failure("validation", "?", None, "PARSE_ERROR",
                               str(exc), "emit a genspec matching the schema"),)
            transcript.append(_record(iteration, "parse_error", failures))
            continue
        except GenSpecValidationError as exc:
            failures = tuple(exc.issues)
            transcript.append(_record(iteration, "invalid", failures))
            continue
        except (ValueError, KeyError, ArithmeticError) as exc:
            # defense-in-depth: any invariant that slipped past validate must refine, not crash
            failures = (Failure("validation", "?", None, "COMPILE_ERROR",
                               str(exc), "produce a genspec that compiles cleanly"),)
            transcript.append(_record(iteration, "compile_error", failures))
            continue

        _require_reference_pools(schema, reference_pools)

        tests = derive_data_tests(genspec, imported, rules)
        verdict = judge_sample(schema, tests, seed=genspec.seed, sample_rows=sample_rows,
                               reference_pools=reference_pools)
        if not verdict.passed:
            failures = verdict.failures
            transcript.append(_record(iteration, "rejected", failures))
            continue

        _run_determinism_gate(schema, genspec.seed, sample_rows, reference_pools)
        transcript.append(_record(iteration, "accepted", ()))
        return GeneratorArtifacts(
            genspec=response.genspec,
            data_tests=tuple(t.to_dict() for t in tests),
            provenance=Provenance(
                provider_id=provider.provider_id,
                iterations=iteration,
                determinism_gate_passed=True,
                genlib_version=seedwright_genlib.__version__,
            ),
        )

    raise AuthoringFailed(transcript, failures)


def _record(iteration: int, outcome: str, failures: tuple[Failure, ...]) -> dict[str, Any]:
    return {"iteration": iteration, "outcome": outcome,
            "failures": [f.to_dict() for f in failures]}


def _require_reference_pools(schema: SchemaSpec, reference_pools: dict[str, Any] | None) -> None:
    pools = reference_pools or {}
    missing = [
        t.name for t in schema.tables
        if t.table_class is TableClass.REFERENCE and t.name not in pools
    ]
    if missing:
        raise ReferencePoolMissing(f"reference tables need key pools (task input): {missing}")


def _run_determinism_gate(
    schema: SchemaSpec, seed: int, sample_rows: int, reference_pools: dict[str, Any] | None
) -> None:
    assert_deterministic(lambda: generate_sample(schema, seed, sample_rows, reference_pools))
