


import ast
import difflib
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ASTDiff:
    """Represents a difference between two AST trees"""
    similarity_ratio: float
    added_nodes: list[str]
    removed_nodes: list[str]
    modified_nodes: list[tuple[str, str]]
    diff_text: str


def parse_code_to_ast(code: str) -> ast.AST | None:
    """Safely parse Python code to AST"""
    try:
        return ast.parse(code)
    except SyntaxError:
        return None


def get_ast_signature(node: ast.AST) -> str:
    """Generate a signature string for an AST node"""
    if isinstance(node, ast.FunctionDef):
        args = [arg.arg for arg in node.args.args]
        return f"func:{node.name}({','.join(args)})"
    elif isinstance(node, ast.ClassDef):
        return f"class:{node.name}"
    elif isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
        return f"import:{','.join(names)}"
    elif isinstance(node, ast.ImportFrom):
        return f"from:{node.module}"
    elif isinstance(node, ast.Assign):
        targets = [ast.dump(t) for t in node.targets]
        return f"assign:{','.join(targets)}"
    return f"{node.__class__.__name__}:{ast.dump(node)[:50]}"


def compute_ast_diff(original_code: str, fixed_code: str) -> ASTDiff:
    """
    Compute structural diff between two code snippets.
    Returns similarity ratio and detailed change information.
    """
    original_ast = parse_code_to_ast(original_code)
    fixed_ast = parse_code_to_ast(fixed_code)
    
    if not original_ast or not fixed_ast:
        # Fallback to text diff if AST parsing fails
        return _text_diff_fallback(original_code, fixed_code)
    
    original_nodes = [get_ast_signature(node) for node in ast.walk(original_ast)]
    fixed_nodes = [get_ast_signature(node) for node in ast.walk(fixed_ast)]
    
    # Compute similarity using SequenceMatcher
    sm = difflib.SequenceMatcher(None, original_nodes, fixed_nodes)
    similarity = sm.ratio()
    
    # Identify changes
    added = []
    removed = []
    modified = []
    
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            added.extend(fixed_nodes[j1:j2])
        elif tag == "delete":
            removed.extend(original_nodes[i1:i2])
        elif tag == "replace":
            for old, new in zip(original_nodes[i1:i2], fixed_nodes[j1:j2]):
                modified.append((old, new))
    
    # Unified text diff
    diff_text = "\n".join(difflib.unified_diff(
        original_code.splitlines(),
        fixed_code.splitlines(),
        lineterm="",
        fromfile="original",
        tofile="fixed"
    ))
    
    return ASTDiff(
        similarity_ratio=similarity,
        added_nodes=added,
        removed_nodes=removed,
        modified_nodes=modified,
        diff_text=diff_text
    )


def _text_diff_fallback(original: str, fixed: str) -> ASTDiff:
    """Fallback text-based diff when AST parsing fails"""
    sm = difflib.SequenceMatcher(None, original.splitlines(), fixed.splitlines())
    diff_text = "\n".join(difflib.unified_diff(
        original.splitlines(),
        fixed.splitlines(),
        lineterm=""
    ))
    return ASTDiff(
        similarity_ratio=sm.ratio(),
        added_nodes=[],
        removed_nodes=[],
        modified_nodes=[],
        diff_text=diff_text
    )


def extract_locators(code: str) -> list[str]:
    """
    Extract UI locators from Playwright/Selenium test code.
    Returns list of locator strings for analysis.
    """
    patterns = [
        r'page\.get_by_\w+\(["\']([^"\']+)["\']\)',
        r'page\.locator\(["\']([^"\']+)["\']\)',
        r'page\.\$\(["\']([^"\']+)["\']\)',
        r'By\.\w+\(["\']([^"\']+)["\']\)',
        r'data-testid=["\']([^"\']+)["\']',
        r'id=["\']([^"\']+)["\']',
        r'class=["\']([^"\']+)["\']',
    ]
    
    locators = []
    for pattern in patterns:
        matches = re.findall(pattern, code)
        locators.extend(matches)
    
    return list(set(locators))


def suggest_locator_strategy(broken_locator: str, dom_snapshot: str | None = None) -> list[str]:
    """
    Suggest alternative locator strategies when one breaks.
    """
    suggestions = []
    
    # If it was an ID selector
    if broken_locator.startswith("#"):
        base = broken_locator[1:]
        suggestions.extend([
            f'[data-testid="{base}"]',
            f'get_by_test_id("{base}")',
            f'get_by_role("button", name="{base}")',
        ])
    
    # If it was a class selector
    elif broken_locator.startswith("."):
        base = broken_locator[1:]
        suggestions.extend([
            f'[data-testid="{base}"]',
            f'text="{base}"',
        ])
    
    # If it was an XPath
    elif broken_locator.startswith("//"):
        suggestions.extend([
            f'get_by_text("{broken_locator.split("/")[-1]}")',
            f'locator("{broken_locator}")',
        ])
    
    # Generic fallback
    suggestions.extend([
        f'get_by_role("button", name=re.compile("{broken_locator}", re.I))',
        f'get_by_text("{broken_locator}", exact=False)',
    ])
    
    return suggestions

