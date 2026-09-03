#!/usr/bin/env python3
"""Saved labels with holes in them.

A template is an ordinary label document whose text carries `{{field}}`
placeholders, plus a declaration of what those fields are. That is the
difference between a designer and the thing people actually use: the
designer is opened once per label *kind*, and after that the job is "sample
id 9912, today's date, print two" — which is one form and one button.

Placeholders are substituted into `text`, `data` and `asset` props and
nowhere else, and the substitution is plain string replacement with no
expression language. That is a deliberate ceiling: a template that can
evaluate is a template that can be made to evaluate something else by
whoever sends the automation payload, and the value of a label expression
language is nearly zero against that.

Two fields are always available without being declared: `{{date}}` and
`{{time}}`, in the machine's own locale-independent form, because "what was
in the freezer on the 3rd" is most of why anything gets a label at all.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import atomic_write

PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")

# Props a placeholder may appear in. Anything else — a font key, a rotation,
# a threshold — is structure, and a template that can rewrite its own
# structure from an automation payload is a different and much larger thing
# than a label with a name on it.
SUBSTITUTED = ("text", "data", "asset")


class UnknownTemplate(KeyError):
    """No template by that id or name. `detail` is what to show."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass
class Field:
    """One hole in a template, as the form that fills it."""

    key: str
    label: str = ""
    default: str = ""
    hint: str = ""
    multiline: bool = False

    def as_dict(self) -> dict:
        data = asdict(self)
        data["label"] = self.label or self.key.replace("_", " ").title()
        return data


@dataclass
class Template:
    id: str
    name: str
    label: dict
    fields: list[Field] = field(default_factory=list)
    description: str = ""
    icon: str = "mdi:label"
    copies: int = 1
    pinned: bool = False
    created_at: float = 0.0
    updated_at: float = 0.0
    use_count: int = 0

    def as_dict(self) -> dict:
        data = asdict(self)
        data["fields"] = [f.as_dict() for f in self.fields]
        data["stock"] = self.label.get("stock", "")
        return data


def builtin_now() -> dict[str, str]:
    """The fields every template gets for free."""
    return {
        "date": time.strftime("%Y-%m-%d"),
        "time": time.strftime("%H:%M"),
        "datetime": time.strftime("%Y-%m-%d %H:%M"),
    }


def placeholders(label: dict) -> list[str]:
    """Every field a label document asks for, in the order it asks.

    Order matters because it is the order of the form, and a form whose
    boxes are in a different order from the label is a form people fill in
    wrong. Sorting alphabetically was the first cut and it put "date" above
    "sample id" on every template.
    """
    seen: list[str] = []
    for element in label.get("elements") or []:
        props = element.get("props") or {}
        for key in SUBSTITUTED:
            for match in PLACEHOLDER.finditer(str(props.get(key, "") or "")):
                name = match.group(1)
                if name not in seen:
                    seen.append(name)
    return seen


def apply_fields(label: dict, values: dict) -> tuple[dict, list[str]]:
    """Fill a template in. Returns the label and any field left empty.

    An unfilled placeholder becomes an empty string rather than staying as
    `{{sample_id}}` on the label — a label that prints its own template
    syntax is worse than one with a gap, because the gap is obvious and the
    braces look deliberate. The names are returned so the caller can say
    which ones were blank; whether that is a refusal or a note is the
    caller's call, and it differs (the panel warns, an automation refuses).
    """
    merged = {**builtin_now(), **{str(k): str(v) for k, v in (values or {}).items()}}
    missing: list[str] = []

    def substitute(text: str) -> str:
        def replace(match: re.Match) -> str:
            name = match.group(1)
            if name not in merged or merged[name] == "":
                if name not in missing:
                    missing.append(name)
                return ""
            return merged[name]
        return PLACEHOLDER.sub(replace, text)

    filled = {**label, "elements": []}
    for element in label.get("elements") or []:
        copy = {**element, "props": dict(element.get("props") or {})}
        for key in SUBSTITUTED:
            if key in copy["props"]:
                copy["props"][key] = substitute(str(copy["props"][key] or ""))
        filled["elements"].append(copy)
    return filled, missing


@dataclass
class TemplateStore:
    path: Path
    _items: dict[str, Template] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.load()

    def load(self) -> None:
        raw = atomic_write.read_json(self.path, {}) or {}
        self._items = {}
        for item in raw.get("templates", []):
            try:
                fields = [Field(**f) for f in item.get("fields", [])]
            except TypeError:
                fields = []
            known = {k: v for k, v in item.items()
                     if k in Template.__dataclass_fields__ and k != "fields"}
            try:
                template = Template(fields=fields, **known)
            except TypeError:
                continue
            self._items[template.id] = template

    def save(self) -> None:
        atomic_write.write_json(self.path, {
            "templates": [t.as_dict() for t in self._items.values()]})

    def all(self) -> list[Template]:
        """Pinned first, then most-used, then newest.

        Most-used rather than most-recent because a label people print
        fifty times a week should not be pushed down the list by one they
        made yesterday and will never open again.
        """
        return sorted(
            self._items.values(),
            key=lambda t: (not t.pinned, -t.use_count, -t.updated_at))

    def get(self, template_id: str) -> Template | None:
        return self._items.get(template_id)

    def by_name(self, name: str) -> Template | None:
        """Case-insensitive lookup — the name is what an automation types."""
        wanted = (name or "").strip().casefold()
        return next((t for t in self._items.values()
                     if t.name.casefold() == wanted), None)

    def resolve(self, ref: str) -> Template:
        found = self.get(ref) or self.by_name(ref)
        if found is None:
            names = ", ".join(f'"{t.name}"' for t in self.all()[:8])
            raise UnknownTemplate(
                f"No template called {ref!r}. Saved templates: "
                f"{names or 'none yet'}.")
        return found

    def put(self, template: Template) -> Template:
        now = time.time()
        if not template.id:
            template.id = uuid.uuid4().hex[:12]
        existing = self._items.get(template.id)
        template.created_at = existing.created_at if existing else now
        template.use_count = existing.use_count if existing else 0
        template.updated_at = now
        self._items[template.id] = template
        self.save()
        return template

    def used(self, template_id: str) -> None:
        template = self._items.get(template_id)
        if template is None:
            return
        template.use_count += 1
        self.save()

    def remove(self, template_id: str) -> bool:
        if self._items.pop(template_id, None) is None:
            return False
        self.save()
        return True
