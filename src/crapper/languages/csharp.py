"""C# methods and cyclomatic complexity.

Entries are methods, constructors, finalizers, operators, and properties or
indexers whose accessors have a body. Auto-properties (`{ get; set; }`) and
bodiless (abstract, interface, partial, extern) members are not entries.
Lambdas and local functions stay inside the enclosing member. The namespace is
`Namespace.Outer.Inner`, which matches coverlet's class names except that
coverlet writes nested types as `Outer/Inner`; coverage joins on file lines.
"""

from crapper.languages.treesitter import (
    complexity,
    end_line,
    node_text,
    parse,
    start_line,
)
from crapper.model import Function

_TYPES = {
    "class_declaration",
    "struct_declaration",
    "record_declaration",
    "record_struct_declaration",
    "interface_declaration",
}
_NAMESPACES = {"namespace_declaration", "file_scoped_namespace_declaration"}
_MEMBERS = {
    "method_declaration",
    "constructor_declaration",
    "destructor_declaration",
    "operator_declaration",
    "conversion_operator_declaration",
}
_ACCESSED = {"property_declaration", "indexer_declaration"}
_DECISIONS = {
    "if_statement",
    "for_statement",
    "foreach_statement",
    "while_statement",
    "do_statement",
    "catch_clause",
    "conditional_expression",
    "switch_section",
    "switch_expression_arm",
    "conditional_access_expression",
    "and_pattern",
    "or_pattern",
}
_LOGIC = {"&&", "||", "??"}
_BODIES = {"block", "arrow_expression_clause"}


def _is_decision(node) -> bool:
    if node.type in _DECISIONS:
        return True
    return node.type == "binary_expression" and any(
        child.type in _LOGIC for child in node.children
    )


def _has_body(node) -> bool:
    return any(child.type in _BODIES for child in node.children)


def _is_entry(node) -> bool:
    if node.type in _MEMBERS:
        return _has_body(node)
    if node.type in _ACCESSED:
        if _has_body(node):
            return True
        accessors = next((c for c in node.children if c.type == "accessor_list"), None)
        return accessors is not None and any(_has_body(a) for a in accessors.children)
    return False


def _name(data: bytes, node) -> str | None:
    if node.type == "indexer_declaration":
        return "this[]"
    if node.type in {"operator_declaration", "conversion_operator_declaration"}:
        params = node.child_by_field_name("parameters")
        text = data[node.start_byte : params.start_byte].decode("utf-8")
        return "operator " + " ".join(text.split("operator", 1)[-1].split())
    ident = node.child_by_field_name("name")
    if ident is None:
        return None
    prefix = "~" if node.type == "destructor_declaration" else ""
    return prefix + node_text(data, ident)


def _namespace(data: bytes, node) -> str | None:
    """Dotted `Namespace.Type.Nested` that holds `node`, or None outside any type."""

    namespaces: list[str] = []
    types: list[str] = []
    current = node.parent
    while current is not None:
        name = current.child_by_field_name("name")
        if current.type in _TYPES and name is not None:
            types.append(node_text(data, name))
        elif current.type in _NAMESPACES and name is not None:
            namespaces.append(node_text(data, name))
        current = current.parent
    if not types:
        return None
    return ".".join(reversed(types + namespaces))


def _file_namespace(data: bytes, root) -> str | None:
    """A file-scoped namespace is a sibling of the types, not their ancestor."""

    for child in root.children:
        if child.type == "file_scoped_namespace_declaration":
            name = child.child_by_field_name("name")
            return node_text(data, name) if name is not None else None
    return None


def functions_in_source(
    source: str, path: str, project_root: str | None = None
) -> list[Function]:
    del project_root
    data, tree = parse(source, "csharp")
    file_namespace = _file_namespace(data, tree.root_node)
    found: list[Function] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if _is_entry(node):
            name = _name(data, node)
            namespace = _namespace(data, node)
            if name and namespace:
                if file_namespace:
                    namespace = f"{file_namespace}.{namespace}"
                found.append(
                    Function(
                        name=name,
                        namespace=namespace,
                        complexity=complexity(node, _is_decision, lambda _: False),
                        start_line=start_line(node),
                        end_line=end_line(node),
                        path=path,
                        language="csharp",
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                    )
                )
            continue
        stack.extend(reversed(node.children))
    return found
