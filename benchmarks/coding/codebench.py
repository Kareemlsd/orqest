"""Mini-CodeBench-Hard: 10 small but genuinely tricky coding problems.

Designed to break single-shot LLM completion. Each problem has subtle edge
cases that even frontier models miss in one shot — but a system that can
run its own code against tests will catch and fix.

Strategy:
- Problems are small (single function, <50 lines of solution)
- Each has adversarial test cases buried in the hidden test set
- A correct one-shot answer requires reading the spec carefully AND
  anticipating non-obvious edge cases

Tests are `(expression, expected)` pairs. The expression is `eval()`'d in
the namespace where the candidate's code has been `exec()`'d.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Problem:
    name: str
    prompt: str
    tests: list[tuple[str, Any]]  # (expression, expected_value)


PROBLEMS: list[Problem] = [
    Problem(
        name="parse_roman",
        prompt=(
            "Implement `parse_roman(s: str) -> int | None`. "
            "Convert a Roman numeral string to integer for 1..3999. "
            "STRICT validation: return None for any invalid Roman numeral. "
            "Rules: I, X, C can appear up to 3 times in a row; V, L, D appear "
            "at most once total; only IV/IX, XL/XC, CD/CM are valid subtractive forms. "
            "'IIII' is invalid (return None). 'VV' is invalid. 'IL' is invalid. "
            "Empty string returns None. Lowercase or mixed case returns None. "
            "Return ONLY the function definition (no imports needed)."
        ),
        tests=[
            ("parse_roman('III')", 3),
            ("parse_roman('IV')", 4),
            ("parse_roman('IX')", 9),
            ("parse_roman('LVIII')", 58),
            ("parse_roman('MCMXCIV')", 1994),
            ("parse_roman('MMMCMXCIX')", 3999),
            ("parse_roman('IIII')", None),
            ("parse_roman('VV')", None),
            ("parse_roman('IL')", None),
            ("parse_roman('IC')", None),
            ("parse_roman('')", None),
            ("parse_roman('iv')", None),
            ("parse_roman('XIIII')", None),
            ("parse_roman('VIII')", 8),
        ],
    ),
    Problem(
        name="parse_csv_row",
        prompt=(
            "Implement `parse_csv_row(line: str) -> list[str]`. "
            "Parse ONE CSV line according to RFC 4180 rules: "
            "- Fields are separated by commas. "
            "- A field may be quoted with double quotes; quoted fields may contain commas. "
            "- Inside a quoted field, a literal double quote is escaped by doubling it: \"\". "
            "- Unquoted fields contain no quotes. "
            "- Empty fields are preserved (a trailing comma produces a trailing empty string). "
            "Examples: 'a,b,c' -> ['a','b','c']; 'a,\"b,c\",d' -> ['a','b,c','d']; "
            "'\"a\"\"b\"' -> ['a\"b']. "
            "Return ONLY the function definition."
        ),
        tests=[
            ("parse_csv_row('a,b,c')", ["a", "b", "c"]),
            ("parse_csv_row('\"a\",\"b\",\"c\"')", ["a", "b", "c"]),
            ("parse_csv_row('a,\"b,c\",d')", ["a", "b,c", "d"]),
            ("parse_csv_row('\"a\"\"b\"')", ['a"b']),
            ("parse_csv_row('a,,c')", ["a", "", "c"]),
            ("parse_csv_row('a,b,')", ["a", "b", ""]),
            ("parse_csv_row(',a')", ["", "a"]),
            ("parse_csv_row('')", [""]),
            ("parse_csv_row('\"hello, world\",foo')", ["hello, world", "foo"]),
            ("parse_csv_row('a,\"b\"\"c\"\"d\",e')", ["a", 'b"c"d', "e"]),
        ],
    ),
    Problem(
        name="text_justify",
        prompt=(
            "Implement `text_justify(words: list[str], width: int) -> list[str]`. "
            "Format words into lines of EXACTLY `width` characters using full justification. "
            "Rules: "
            "- Pack as many words into each line as possible (greedy). "
            "- Distribute extra spaces between words EVENLY. If spaces can't be divided "
            "  evenly, give extra space to the LEFTmost gaps first. "
            "- The LAST line is left-justified (single space between words, padded with "
            "  trailing spaces to reach `width`). "
            "- A line with only one word is left-justified (pad trailing spaces). "
            "Return ONLY the function definition. No imports needed."
        ),
        tests=[
            (
                "text_justify(['This', 'is', 'an', 'example', 'of', 'text', 'justification.'], 16)",
                ["This    is    an", "example  of text", "justification.  "],
            ),
            (
                "text_justify(['What','must','be','acknowledgment','shall','be'], 16)",
                ["What   must   be", "acknowledgment  ", "shall be        "],
            ),
            (
                "text_justify(['Hello'], 10)",
                ["Hello     "],
            ),
            (
                "text_justify(['a','b','c','d','e'], 3)",
                ["a b", "c d", "e  "],
            ),
            (
                "text_justify(['Science','is','what','we','understand'], 20)",
                ["Science  is  what we", "understand          "],
            ),
        ],
    ),
    Problem(
        name="min_window_substring",
        prompt=(
            "Implement `min_window_substring(s: str, t: str) -> str`. "
            "Return the shortest substring of `s` that contains every character of `t` "
            "(counting multiplicities — if t has two 'a's, the window must too). "
            "If no such window exists, return ''. If multiple shortest windows exist, "
            "return the leftmost one. "
            "Examples: s='ADOBECODEBANC', t='ABC' -> 'BANC'. "
            "Return ONLY the function definition. No imports needed."
        ),
        tests=[
            ("min_window_substring('ADOBECODEBANC', 'ABC')", "BANC"),
            ("min_window_substring('a', 'a')", "a"),
            ("min_window_substring('a', 'aa')", ""),
            ("min_window_substring('aaab', 'aab')", "aab"),
            ("min_window_substring('', 'a')", ""),
            ("min_window_substring('abcabdebac', 'cda')", "cabd"),
            ("min_window_substring('abc', '')", ""),
            ("min_window_substring('xyz', 'xyzz')", ""),
        ],
    ),
    Problem(
        name="regex_match",
        prompt=(
            "Implement `regex_match(s: str, pattern: str) -> bool`. "
            "Implement a minimal regex matcher supporting ONLY: "
            "- '.' matches any single character "
            "- 'X*' matches zero or more of the preceding element X (where X is a "
            "  single character or '.') "
            "The match must be against the ENTIRE string s, not a substring. "
            "Return True iff the pattern matches s exactly. "
            "Return ONLY the function definition. No imports of `re` or anything else."
        ),
        tests=[
            ("regex_match('aa', 'a')", False),
            ("regex_match('aa', 'a*')", True),
            ("regex_match('ab', '.*')", True),
            ("regex_match('aab', 'c*a*b')", True),
            ("regex_match('mississippi', 'mis*is*p*.')", False),
            ("regex_match('', '')", True),
            ("regex_match('', 'a*')", True),
            ("regex_match('a', '.')", True),
            ("regex_match('aaa', 'a*a')", True),
            ("regex_match('aaa', 'ab*ac*a')", True),
            ("regex_match('aaca', 'ab*a*c*a')", True),
            ("regex_match('a', 'ab*')", True),
        ],
    ),
    Problem(
        name="largest_rectangle_in_histogram",
        prompt=(
            "Implement `largest_rectangle_in_histogram(heights: list[int]) -> int`. "
            "Given the heights of bars in a histogram (all bars have width 1), return "
            "the area of the largest rectangle that can be formed within the histogram. "
            "Heights are non-negative integers. Empty list returns 0. "
            "Must be efficient — naive O(n²) is too slow for n=10⁵. Use a monotonic stack. "
            "Return ONLY the function definition. No imports needed."
        ),
        tests=[
            ("largest_rectangle_in_histogram([2,1,5,6,2,3])", 10),
            ("largest_rectangle_in_histogram([2,4])", 4),
            ("largest_rectangle_in_histogram([])", 0),
            ("largest_rectangle_in_histogram([0])", 0),
            ("largest_rectangle_in_histogram([5])", 5),
            ("largest_rectangle_in_histogram([1,1,1,1,1])", 5),
            ("largest_rectangle_in_histogram([4,2,0,3,2,5])", 6),
            ("largest_rectangle_in_histogram([6,7,5,2,4,5,9,3])", 16),
        ],
    ),
    Problem(
        name="word_ladder_length",
        prompt=(
            "Implement `word_ladder_length(begin: str, end: str, dictionary: list[str]) -> int`. "
            "Find the length of the shortest transformation sequence from `begin` to `end` "
            "such that each intermediate word differs from the previous by exactly one letter "
            "AND each intermediate word is in `dictionary`. The length counts every word "
            "INCLUDING both endpoints. `end` must be in `dictionary` to be reachable. "
            "`begin` is NOT required to be in dictionary. "
            "Return 0 if no such sequence exists. All words are the same length and lowercase. "
            "Examples: word_ladder_length('hit','cog',['hot','dot','dog','lot','log','cog']) -> 5 "
            "(hit->hot->dot->dog->cog). "
            "Return ONLY the function definition. `from collections import deque` is allowed."
        ),
        tests=[
            ("word_ladder_length('hit', 'cog', ['hot','dot','dog','lot','log','cog'])", 5),
            ("word_ladder_length('hit', 'cog', ['hot','dot','dog','lot','log'])", 0),
            ("word_ladder_length('a', 'c', ['a','b','c'])", 2),
            ("word_ladder_length('cat', 'cat', ['cat'])", 1),
            ("word_ladder_length('cat', 'dog', ['cot','cog','dog'])", 4),
            ("word_ladder_length('lost', 'cost', ['cost'])", 2),
            ("word_ladder_length('lost', 'cost', [])", 0),
        ],
    ),
    Problem(
        name="edit_distance",
        prompt=(
            "Implement `edit_distance(s1: str, s2: str) -> int`. "
            "Compute the Levenshtein distance: minimum number of single-character "
            "insertions, deletions, or substitutions to transform s1 into s2. "
            "Return ONLY the function definition. No imports needed."
        ),
        tests=[
            ("edit_distance('kitten', 'sitting')", 3),
            ("edit_distance('', '')", 0),
            ("edit_distance('abc', '')", 3),
            ("edit_distance('', 'abc')", 3),
            ("edit_distance('abc', 'abc')", 0),
            ("edit_distance('horse', 'ros')", 3),
            ("edit_distance('intention', 'execution')", 5),
            ("edit_distance('a', 'b')", 1),
            ("edit_distance('abc', 'yabd')", 2),
        ],
    ),
    Problem(
        name="subarray_sum_equals_k",
        prompt=(
            "Implement `subarray_sum_equals_k(nums: list[int], k: int) -> int`. "
            "Return the number of contiguous subarrays of `nums` whose sum equals `k`. "
            "Nums can contain negative numbers and zeros. Subarrays of length 1 count. "
            "Must be O(n) using the prefix-sum + hashmap trick — O(n²) is too slow for n=10⁴. "
            "Examples: subarray_sum_equals_k([1,1,1], 2) -> 2; subarray_sum_equals_k([1,-1,0], 0) -> 3. "
            "Return ONLY the function definition. No imports needed."
        ),
        tests=[
            ("subarray_sum_equals_k([1,1,1], 2)", 2),
            ("subarray_sum_equals_k([1,2,3], 3)", 2),
            ("subarray_sum_equals_k([1,-1,0], 0)", 3),
            ("subarray_sum_equals_k([], 0)", 0),
            ("subarray_sum_equals_k([0,0,0], 0)", 6),
            ("subarray_sum_equals_k([1], 0)", 0),
            ("subarray_sum_equals_k([1], 1)", 1),
            ("subarray_sum_equals_k([3,4,7,2,-3,1,4,2], 7)", 4),
            ("subarray_sum_equals_k([-1,-1,1], 0)", 1),
        ],
    ),
    Problem(
        name="palindrome_partition_min_cuts",
        prompt=(
            "Implement `palindrome_partition_min_cuts(s: str) -> int`. "
            "Return the MINIMUM number of cuts needed so that every resulting substring is a palindrome. "
            "A single character is a palindrome (zero cuts needed for length-1 strings). "
            "Empty string returns 0. "
            "Examples: 'aab' -> 1 (cut into 'aa' + 'b'); 'a' -> 0; 'ab' -> 1; 'aba' -> 0. "
            "Must be efficient — O(n²) DP works; naive O(2^n) does not. "
            "Return ONLY the function definition. No imports needed."
        ),
        tests=[
            ("palindrome_partition_min_cuts('aab')", 1),
            ("palindrome_partition_min_cuts('a')", 0),
            ("palindrome_partition_min_cuts('')", 0),
            ("palindrome_partition_min_cuts('ab')", 1),
            ("palindrome_partition_min_cuts('aba')", 0),
            ("palindrome_partition_min_cuts('abba')", 0),
            ("palindrome_partition_min_cuts('abcba')", 0),
            ("palindrome_partition_min_cuts('abcdef')", 5),
            ("palindrome_partition_min_cuts('coder')", 4),
            ("palindrome_partition_min_cuts('aabaa')", 0),
        ],
    ),
]


def score_candidate(code: str, problem: Problem) -> dict:
    """Run candidate code against hidden tests. Returns dict with score + errors.

    Runs in-process via exec(). For the COMBO path we use SubprocessSandbox.
    """
    result = {
        "problem": problem.name,
        "passed": 0,
        "total": len(problem.tests),
        "errors": [],
        "compile_error": None,
    }

    namespace: dict = {}
    try:
        exec(code, namespace)
    except Exception as exc:  # noqa: BLE001
        result["compile_error"] = f"{type(exc).__name__}: {exc}"
        return result

    for expression, expected in problem.tests:
        try:
            actual = eval(expression, namespace)
            if actual == expected:
                result["passed"] += 1
            else:
                result["errors"].append(
                    {"expr": expression, "expected": expected, "actual": actual}
                )
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(
                {"expr": expression, "expected": expected, "actual": f"<{type(exc).__name__}: {exc}>"}
            )

    return result


def aggregate(results: list[dict]) -> dict:
    n_problems = len(results)
    n_full_pass = sum(1 for r in results if r["passed"] == r["total"] and not r["compile_error"])
    total_tests = sum(r["total"] for r in results)
    passed_tests = sum(r["passed"] for r in results)
    return {
        "pass_at_1": n_full_pass / n_problems if n_problems else 0.0,
        "test_pass_rate": passed_tests / total_tests if total_tests else 0.0,
        "n_problems": n_problems,
        "n_full_pass": n_full_pass,
        "passed_tests": passed_tests,
        "total_tests": total_tests,
    }


def visible_examples_for(problem: Problem, k: int = 2) -> list[tuple[str, Any]]:
    """Return the first k tests as PUBLIC examples (visible to the agent).

    The remaining tests are hidden — used only by score_candidate.
    """
    return problem.tests[:k]


def hidden_count(problem: Problem) -> int:
    return max(0, len(problem.tests) - 2)


if __name__ == "__main__":
    print(f"Loaded {len(PROBLEMS)} problems")
    for p in PROBLEMS:
        print(f"  - {p.name}: {len(p.tests)} tests")
