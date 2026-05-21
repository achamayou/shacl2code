#
# Copyright (c) 2026 Joshua Watt
#
# SPDX-License-Identifier: MIT
"""CDDL schema renderer"""

import re

from rdflib.namespace import SH

from .common import BasicJinjaRender
from .lang import TEMPLATE_DIR, language

DATATYPE_MAP = {
    "http://www.w3.org/2001/XMLSchema#string": "tstr",
    "http://www.w3.org/2001/XMLSchema#anyURI": "anyURI",
    "http://www.w3.org/2001/XMLSchema#integer": "int",
    "http://www.w3.org/2001/XMLSchema#nonNegativeInteger": "uint",
    "http://www.w3.org/2001/XMLSchema#positiveInteger": "uint .ge 1",
    "http://www.w3.org/2001/XMLSchema#boolean": "bool",
    # Keep decimal string-compatible with SPDX JSON mapping conventions
    "http://www.w3.org/2001/XMLSchema#decimal": 'tstr .regexp "-?[0-9]+(\\\\.[0-9]*)?"',
    # CoSPDX style CBOR-first encoding for time values
    "http://www.w3.org/2001/XMLSchema#dateTime": "#6.1(uint)",
    "http://www.w3.org/2001/XMLSchema#dateTimeStamp": "#6.1(uint)",
}


def _sanitize_name(name):
    name = re.sub(r"[^a-zA-Z0-9_]", "_", str(name))
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = "value"
    if name[0].isdigit():
        name = "_" + name
    return name


def _escape_string(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


class SymbolMap:
    def __init__(self, prefix):
        self._prefix = prefix
        self._symbols = {}
        self._used = set()

    def add(self, key, preferred):
        if key in self._symbols:
            return self._symbols[key]

        base = f"{self._prefix}.{_sanitize_name(preferred)}"
        sym = base
        suffix = 2
        while sym in self._used:
            sym = f"{base}_{suffix}"
            suffix += 1
        self._symbols[key] = sym
        self._used.add(sym)
        return sym

    def get(self, key):
        return self._symbols[key]


def _list_occurrence(prop):
    min_count = 0 if prop.min_count is None else prop.min_count
    max_count = prop.max_count

    if min_count == 0 and max_count is None:
        return "*"
    if min_count == 1 and max_count is None:
        return "+"
    return f"{min_count if min_count else ''}*{'' if max_count is None else max_count}"


@language("cddl")
class CddlRender(BasicJinjaRender):
    HELP = "CDDL Schema (native CBOR first)"

    def __init__(self, args):
        super().__init__(args, TEMPLATE_DIR / "cddl.j2")

    def get_additional_render_args(self, model):
        classes_by_id = {c._id: c for c in model.classes}

        class_names = {}
        used_class_names = set()
        for c in model.classes:
            base = _sanitize_name("_".join(c.clsname))
            name = base
            suffix = 2
            while name in used_class_names:
                name = f"{base}_{suffix}"
                suffix += 1
            used_class_names.add(name)
            class_names[c._id] = name

        label_symbols = SymbolMap("label")
        const_symbols = SymbolMap("const")
        label_alias_by_term = {
            "@graph": "label.@graph",
            "type": "label.type",
            "@id": "label.@id",
        }

        def add_label(term):
            if term in label_alias_by_term:
                return label_alias_by_term[term]
            alias = label_symbols.add(term, term)
            label_alias_by_term[term] = alias
            return alias

        def add_const(term):
            return const_symbols.add(term, term)

        def class_const_alias(c):
            return add_const(model.context.compact_vocab(c._id))

        for c in model.classes:
            class_const_alias(c)
            if c.id_property:
                add_label(c.id_property)
            for p in c.properties:
                add_label(model.context.compact_vocab(p.path))
                if p.enum_values:
                    for value in p.enum_values:
                        add_const(model.context.compact_vocab(value, p.path))
            for ni in c.named_individuals:
                add_const(model.context.compact_iri(ni._id))

        def all_derived_ids(c):
            d = set()

            def recurse(cls):
                for derived in cls.derived_ids:
                    if derived in d:
                        continue
                    d.add(derived)
                    recurse(classes_by_id[derived])

            recurse(c)
            return sorted(d)

        class_defs = []
        for c in model.classes:
            class_name = class_names[c._id]
            type_const = class_const_alias(c)

            id_label = "label.@id" if not c.id_property else add_label(c.id_property)
            id_optional = c.node_kind != SH.IRI
            if c.node_kind == SH.BlankNode:
                id_type = "BlankNode"
            elif c.node_kind == SH.IRI:
                id_type = "IRI"
            else:
                id_type = "BlankNodeOrIRI"

            prop_defs = []
            prop_entries = []
            used_prop_names = set()
            for p in c.properties:
                prop_name = _sanitize_name(f"prop_{class_name}_{p.varname}")
                while prop_name in used_prop_names:
                    prop_name += "_2"
                used_prop_names.add(prop_name)

                if p.enum_values:
                    enum_types = [
                        add_const(model.context.compact_vocab(v, p.path))
                        for v in p.enum_values
                    ]
                    enum_types = list(dict.fromkeys(enum_types))
                    prop_type = " / ".join(enum_types)
                elif p.class_id:
                    prop_type = f"{class_names[p.class_id]}_derived"
                else:
                    prop_type = DATATYPE_MAP.get(p.datatype)
                    if prop_type is None:
                        raise ValueError(f"Unknown data type {p.datatype}")
                    if p.pattern:
                        if p.datatype in (
                            "http://www.w3.org/2001/XMLSchema#string",
                            "http://www.w3.org/2001/XMLSchema#anyURI",
                        ):
                            prop_type = f'{prop_type.split(" .regexp ")[0]} .regexp "{_escape_string(p.pattern)}"'

                prop_defs.append(
                    {
                        "name": prop_name,
                        "type": prop_type,
                    }
                )

                required = (p.min_count or 0) > 0
                label_alias = add_label(model.context.compact_vocab(p.path))
                is_list = p.max_count is None or p.max_count != 1
                if is_list:
                    occurrence = _list_occurrence(p)
                    value_expr = f"[ {occurrence} {prop_name} ]"
                else:
                    value_expr = prop_name
                prop_entries.append(
                    {
                        "label": label_alias,
                        "optional": not required,
                        "value": value_expr,
                    }
                )

            parent_refs = (
                [f"{class_names[p]}_props" for p in c.parent_ids]
                if c.parent_ids
                else ["~SHACLClass"]
            )
            if c.is_extensible:
                parent_refs = [*parent_refs, "~AnyObject"]

            derived_choices = []
            for class_id in [c._id, *all_derived_ids(c)]:
                d = classes_by_id[class_id]
                d_name = class_names[class_id]
                if not d.is_abstract:
                    derived_choices.append(d_name)
                elif d.is_extensible:
                    derived_choices.append(f"{d_name}_props")
                for ni in d.named_individuals:
                    derived_choices.append(add_const(model.context.compact_iri(ni._id)))

            derived_choices.append("BlankNodeOrIRI")
            derived_choices = list(dict.fromkeys(derived_choices))

            class_defs.append(
                {
                    "name": class_name,
                    "type_const": type_const,
                    "id_label": id_label,
                    "id_optional": id_optional,
                    "id_type": id_type,
                    "prop_defs": prop_defs,
                    "prop_entries": prop_entries,
                    "parent_refs": parent_refs,
                    "derived_choices": derived_choices,
                }
            )

        label_entries = [
            {"name": "label.@graph", "value": 1, "term": "@graph"},
            {"name": "label.type", "value": 2, "term": "type"},
            {"name": "label.@id", "value": 3, "term": "@id"},
        ]
        extra_labels = sorted(
            (
                {"name": alias, "term": term}
                for term, alias in label_alias_by_term.items()
                if term not in {"@graph", "type", "@id"}
            ),
            key=lambda item: item["name"],
        )
        for idx, item in enumerate(extra_labels, start=4):
            item["value"] = idx
            label_entries.append(item)

        const_entries = sorted(
            (
                {"name": alias, "term": term}
                for term, alias in const_symbols._symbols.items()
            ),
            key=lambda item: item["name"],
        )
        for idx, item in enumerate(const_entries, start=1001):
            item["value"] = idx

        any_class_choices = []
        for c in model.classes:
            if not c.is_abstract:
                any_class_choices.append(class_names[c._id])
            elif c.is_extensible:
                any_class_choices.append(f"{class_names[c._id]}_props")

        label_type_socket = [class_const_alias(c) for c in model.classes]

        return {
            "class_defs": class_defs,
            "label_entries": label_entries,
            "const_entries": const_entries,
            "any_class_choices": any_class_choices,
            "label_type_socket": label_type_socket,
        }
