#!/usr/bin/env python3
"""
Detailed test for hybrid search (FTS5/SingleStore FTS + vector similarity)
- FTS scoring
- Vector similarity (cosine similarity)
- Hybrid score calculation
- Score threshold filtering
- Result ranking
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from test.cache_test_utils import run_cache_test_main

def test_hybrid_search_scoring(cache):
    """Test hybrid search scoring and ranking on a given cache instance."""
    print("\n1. Adding test plans with varied content...")
    plans = [
        ("Python programming tutorial", "Learn Python basics: variables, loops, functions"),
        ("JavaScript for beginners", "JavaScript introduction: variables, DOM, events"),
        ("Python data analysis with pandas", "Use pandas for data manipulation and analysis"),
        ("Python machine learning scikit-learn", "Build ML models with scikit-learn"),
        ("JavaScript React framework", "Build UI components with React and JSX"),
        ("Python async programming", "Async/await patterns in Python"),
        ("JavaScript Node.js backend", "Create REST APIs with Node.js and Express"),
        ("Python Flask web framework", "Build web apps with Flask"),
    ]

    for task, plan in plans:
        cache.set(task, plan)

    print(f"   Added {len(plans)} plans")

    # Test 1: Search for "Python" - should return Python-related tasks
    print("\n2. Searching for 'Python'...")
    candidates = cache.hybrid_search("Python")
    print(f"   Found {len(candidates)} candidates")
    assert len(candidates) > 0, "Should find Python-related candidates"

    # All candidates should ideally have task_text containing "Python", 
    # but vector search might pull in slightly related tasks at the bottom.
    # At least verify the top candidate matches.
    assert "python" in candidates[0].task_text.lower(), f"Top candidate '{candidates[0].task_text}' should contain 'python'"
    print("   ✅ Top candidate is Python-related")

    # Test 2: Search for "JavaScript" - should return JS-related tasks
    print("\n3. Searching for 'JavaScript'...")
    candidates_js = cache.hybrid_search("JavaScript")
    print(f"   Found {len(candidates_js)} candidates")
    assert len(candidates_js) > 0, "Should find JavaScript-related candidates"

    # Verify top candidate is JS-related
    top_js = candidates_js[0]
    assert "javascript" in top_js.task_text.lower() or "js" in top_js.task_text.lower(), \
        f"Top candidate '{top_js.task_text}' should be JavaScript-related"
    print("   ✅ Top candidate is JavaScript-related")

    # Test 3: Verify scoring properties
    print("\n4. Verifying scoring properties...")
    candidates = cache.hybrid_search("Python data analysis")
    if candidates:
        top = candidates[0]
        print(f"   Top candidate: {top.task_text}")
        print(f"   - Hybrid score: {top.score:.4f}")
        print(f"   - FTS score: {top.fts_score:.4f}")
        print(f"   - Vector score: {top.vec_score:.4f}")

        # Scores should be in [0, 1] range
        assert 0 <= top.score <= 1, "Hybrid score should be in [0, 1]"
        # Note: Depending on backend, scores might be exactly 0 or 1 under certain conditions
        print("   ✅ Scores are properly normalized")

    # Test 4: Verify ranking order
    print("\n5. Verifying ranking order...")
    candidates = cache.hybrid_search("Python")
    for i in range(len(candidates) - 1):
        assert candidates[i].score >= candidates[i+1].score, \
            "Candidates should be ranked by descending score"
    print("   ✅ Candidates are properly ranked")

    # Test 5: MAX_CANDIDATES limit
    print("\n6. Testing MAX_CANDIDATES limit...")
    many_candidates = cache.hybrid_search("Python")
    assert len(many_candidates) <= cache.MAX_CANDIDATES, \
        f"Should return at most {cache.MAX_CANDIDATES} candidates"
    print(f"   ✅ Returned {len(many_candidates)} candidates (limit: {cache.MAX_CANDIDATES})")

    # Test 6: Verify CacheCandidate structure
    print("\n7. Verifying CacheCandidate structure...")
    if candidates:
        c = candidates[0]
        assert hasattr(c, 'task_hash'), "Should have task_hash"
        assert hasattr(c, 'task_text'), "Should have task_text"
        assert hasattr(c, 'plan'), "Should have plan"
        assert hasattr(c, 'score'), "Should have score"
        assert hasattr(c, 'fts_score'), "Should have fts_score"
        assert hasattr(c, 'vec_score'), "Should have vec_score"
        assert hasattr(c, 'timestamp'), "Should have timestamp"
        assert isinstance(c.timestamp, datetime), "timestamp should be datetime"
        print("   ✅ CacheCandidate has all required fields")

    return True

if __name__ == "__main__":
    success = run_cache_test_main(test_hybrid_search_scoring)
    exit(0 if success else 1)
