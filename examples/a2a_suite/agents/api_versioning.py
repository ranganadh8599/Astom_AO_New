"""API versioning agent: strategy, deprecation and compatibility."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "api-versioning",
    skills=(
        Skill(
            id="strategy",
            name="Versioning strategy",
            description=(
                "URI versus media-type versioning, semantic versioning and what counts as a "
                "breaking change."
            ),
            tags=("versioning", "semver", "media-type"),
            keywords=(
                "version", "versioning", "uri", "url", "header", "media", "type", "semver",
                "semantic", "major", "minor", "patch", "breaking", "contract", "v1", "v2",
            ),
            text=(
                "URI versioning (/v1/orders) is the easiest to route and cache but makes the "
                "version part of every URL; media-type versioning (Accept: "
                "application/vnd.acme.v2+json) keeps URLs stable but is harder to debug and "
                "cache. Version the *contract*, not the deployment. A breaking change is "
                "removing or renaming a field, changing a type, tightening validation or "
                "changing status codes; adding an optional field or a new endpoint is not."
            ),
        ),
        Skill(
            id="deprecation",
            name="Deprecation",
            description=(
                "Deprecation and Sunset headers, notice periods and measuring remaining "
                "traffic."
            ),
            tags=("deprecation", "sunset", "notice"),
            keywords=(
                "deprecate", "deprecation", "deprecated", "sunset", "notice", "migration",
                "breaking", "removal", "retire", "timeline", "warning", "header",
            ),
            text=(
                "Announce deprecation with a Deprecation header (RFC 9745) carrying the date, "
                "and a Sunset header (RFC 8594) with the date the endpoint stops working. "
                "Publish a migration guide and instrument old-version usage before announcing; "
                "you cannot retire what you cannot measure. Typical notice is 6-12 months for "
                "external APIs and 30-90 days internal, and the last 90 days should be "
                "accompanied by client contact, not just headers."
            ),
        ),
        Skill(
            id="compatibility",
            name="Backward compatibility",
            description=(
                "Tolerant reader, additive change, unknown enum values and never reusing field "
                "names."
            ),
            tags=("compatibility", "tolerant-reader", "additive"),
            keywords=(
                "compatible", "compatibility", "backward", "forward", "additive", "tolerant",
                "reader", "ignore", "unknown", "enum", "nullable", "optional", "reuse",
                "rename", "schema",
            ),
            text=(
                "Consumers should ignore unknown fields (tolerant reader) and treat enums as "
                "open sets, so a new value does not crash them. Producers add optional fields, "
                "never remove or rename one in place, and never reuse a field name for a "
                "different meaning. Make new fields nullable or defaulted, and design new "
                "endpoints rather than changing the semantics of an existing one. Contract "
                "tests on both sides catch most accidental breaks."
            ),
        ),
    ),
)
