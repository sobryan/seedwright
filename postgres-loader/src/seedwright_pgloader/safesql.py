"""Identifier + namespace safety — the injection keystone (spec FR-L).

Imported schema/table/column names are untrusted input. Every DDL/COPY/teardown builder
composes identifiers through here (never string interpolation), and the Dataset namespace
is validated here before it can appear in a `CREATE`/`DROP SCHEMA`. The mandatory ``ds_``
prefix is what makes a namespace collide-proof with a real application schema, so a scoped
``DROP SCHEMA ds_… CASCADE`` can never destroy ``public`` or an app schema (FR-L.3).
"""

from __future__ import annotations

import hashlib
import os
import re

from psycopg import sql

NAMESPACE_PREFIX = "ds_"
_NAMESPACE_RE = re.compile(r"^ds_[a-z0-9_]+$")
MAX_IDENTIFIER_BYTES = 63  # Postgres NAMEDATALEN-1; longer names are silently truncated.

# Defense-in-depth: these can't match the ds_ pattern anyway, but we refuse them explicitly.
_RESERVED = frozenset({"public", "pg_catalog", "information_schema", "pg_toast"})


class UnsafeNamespaceError(ValueError):
    """A Dataset namespace failed validation — refused before it can reach any DDL."""


class UnsafeIdentifierError(ValueError):
    """A table/column identifier is unusable (empty, contains NUL, or too long)."""


class UnsafeTableNameError(ValueError):
    """A table name is unsafe to use as a filesystem path segment (traversal/separator)."""


def validate_namespace(namespace: str) -> str:
    """Return ``namespace`` if it is a safe Dataset schema name, else raise.

    Requires the ``ds_`` prefix, lowercase ``[a-z0-9_]`` only, ≤63 UTF-8 bytes, and not a
    reserved schema name.
    """
    if namespace in _RESERVED or namespace.startswith("pg_"):
        raise UnsafeNamespaceError(f"reserved schema name: {namespace!r}")
    if not _NAMESPACE_RE.fullmatch(namespace):
        raise UnsafeNamespaceError(
            f"namespace {namespace!r} must match {_NAMESPACE_RE.pattern} "
            f"(mandatory {NAMESPACE_PREFIX!r} prefix, lowercase alnum/underscore)"
        )
    if len(namespace.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise UnsafeNamespaceError(
            f"namespace {namespace!r} exceeds {MAX_IDENTIFIER_BYTES} bytes "
            "(Postgres would silently truncate it)"
        )
    return namespace


def identifier(name: str) -> sql.Identifier:
    """Compose a single SQL identifier safely (double-quoted, embedded quotes doubled).

    Rejects the cases quoting cannot make safe: empty, embedded NUL, or over-length.
    """
    if not name:
        raise UnsafeIdentifierError("empty identifier")
    if "\x00" in name:
        raise UnsafeIdentifierError("identifier contains NUL")
    if len(name.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise UnsafeIdentifierError(
            f"identifier {name!r} exceeds {MAX_IDENTIFIER_BYTES} bytes"
        )
    return sql.Identifier(name)


def qualified(namespace: str, table: str) -> sql.Identifier:
    """Compose a ``"<namespace>"."<table>"`` reference, validating both parts."""
    validate_namespace(namespace)
    identifier(table)  # validate table too; sql.Identifier(a, b) handles the join
    return sql.Identifier(namespace, table)


def validate_relname(name: str) -> str:
    """Return ``name`` if it is safe as a single filesystem path segment, else raise.

    Table names are untrusted (imported schema). They are used to build the Parquet file path,
    so a name containing a path separator or ``.``/``..`` could escape the canonical directory.
    """
    if not name or name in (".", ".."):
        raise UnsafeTableNameError(f"unsafe table name: {name!r}")
    if "\x00" in name or "/" in name or "\\" in name:
        raise UnsafeTableNameError(f"table name {name!r} contains a path separator or NUL")
    if os.sep in name or (os.altsep and os.altsep in name):
        raise UnsafeTableNameError(f"table name {name!r} contains a path separator")
    if len(name.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise UnsafeTableNameError(f"table name {name!r} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return name


_DIGEST_HEX = 16  # 8-byte BLAKE2b digest -> 16 hex chars


def namespace_for(dataset_id: str) -> str:
    """Build a valid ``ds_`` namespace from an arbitrary dataset id (deterministic, collision-free).

    A digest of the *full* id is appended so two distinct ids can never collapse to the same
    namespace (which, in replace mode, would let one Dataset's load drop another's schema). The
    readable slug is truncated to leave room for the digest within Postgres's 63-byte limit.
    """
    digest = hashlib.blake2b(dataset_id.encode("utf-8"), digest_size=8).hexdigest()
    slug_budget = MAX_IDENTIFIER_BYTES - len(NAMESPACE_PREFIX) - 1 - _DIGEST_HEX
    slug = re.sub(r"[^a-z0-9_]+", "_", dataset_id.lower()).strip("_")[:slug_budget].strip("_")
    namespace = f"{NAMESPACE_PREFIX}{slug or 'x'}_{digest}"
    return validate_namespace(namespace)
