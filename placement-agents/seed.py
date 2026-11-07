"""Seed the roadmap. Run:  python seed.py   (safe to re-run)
Add more problems later:  python seed.py my_problems.csv   (columns: topic,name,difficulty,source)
Edit JAVA_TOPICS to match your Udemy course section names.
"""
import csv
import sys
import db

# Udemy course "Data Structures & Algorithms in Java" (49 sections, 46h38m), in course order.
# Small exercise-only sections are merged into their parent topic.
JAVA_TOPICS = [
    "Course intro: what are data structures & algorithms",
    "Big O notation and complexity analysis",
    "Arrays (1D and 2D) theory",
    "Arrays projects (temperature) + array exercises (LeetCode 26/121/1/217/48)",
    "ArrayList",
    "Time complexity practice questions (Q1-Q7)",
    "Singly Linked List",
    "Singly Linked List exercises",
    "Circular Singly Linked List + exercises",
    "Doubly Linked List",
    "Circular Doubly Linked List + array vs linked list",
    "Linked List interview questions (remove dups, nth to last, partition, sum lists, intersection)",
    "Stack (array + linked list) + exercises",
    "Queue (linear, circular, linked list)",
    "Stack and Queue interview questions",
    "Recursion",
    "Recursion exercises",
    "Binary Tree (+ iterative traversals)",
    "Binary Search Tree",
    "AVL Tree",
    "Binary Heap",
    "Trie",
    "Hashing",
    "Sorting algorithms",
    "Searching algorithms",
    "Graphs: terminology, representation (matrix and list)",
    "Graph traversal: BFS and DFS",
    "Topological Sort",
    "Single source shortest path: BFS and Dijkstra",
    "Bellman-Ford",
    "All pairs shortest path: Floyd-Warshall",
    "Minimum Spanning Tree: Disjoint Set, Kruskal, Prim",
    "Tree and graph interview questions",
    "Greedy algorithms",
    "Divide and Conquer",
    "Dynamic Programming: memoization, tabulation",
    "Dynamic Programming problems",
    "Problem-solving method (5 steps)",
    "Backtracking and N-Queens",
    # NOT covered by that course. Delete these lines if you learned core Java elsewhere.
    "Java core: OOP (classes, inheritance, polymorphism, interfaces)",
    "Java core: exceptions, generics, Comparable/Comparator",
    "Java core: Collections framework (List, Set, Map, Deque, PriorityQueue)",
    "Java core: lambdas and Streams",
]

# (topic, name, difficulty) - Striver SDE-sheet style order. 'source' = Striver.
# This is a starter set; import the full sheet via CSV.
P = [
 ("Arrays", "Set Matrix Zeroes", "M"), ("Arrays", "Pascal's Triangle", "E"),
 ("Arrays", "Next Permutation", "M"), ("Arrays", "Maximum Subarray", "M"),
 ("Arrays", "Sort Colors", "M"), ("Arrays", "Best Time to Buy and Sell Stock", "E"),
 ("Arrays", "Rotate Image", "M"), ("Arrays", "Merge Intervals", "M"),
 ("Arrays", "Merge Sorted Array", "E"), ("Arrays", "Find the Duplicate Number", "M"),
 ("Arrays", "Majority Element", "E"), ("Arrays", "Majority Element II", "M"),
 ("Arrays", "Unique Paths", "M"), ("Arrays", "Reverse Pairs", "H"),
 ("Arrays", "Two Sum", "E"), ("Arrays", "3Sum", "M"), ("Arrays", "4Sum", "M"),
 ("Arrays", "Longest Consecutive Sequence", "M"), ("Arrays", "Subarray Sum Equals K", "M"),
 ("Linked List", "Reverse Linked List", "E"), ("Linked List", "Middle of the Linked List", "E"),
 ("Linked List", "Merge Two Sorted Lists", "E"), ("Linked List", "Remove Nth Node From End of List", "M"),
 ("Linked List", "Add Two Numbers", "M"), ("Linked List", "Linked List Cycle", "E"),
 ("Linked List", "Linked List Cycle II", "M"), ("Linked List", "Palindrome Linked List", "E"),
 ("Linked List", "Intersection of Two Linked Lists", "E"), ("Linked List", "Copy List with Random Pointer", "M"),
 ("Linked List", "Reverse Nodes in k-Group", "H"), ("Linked List", "Flatten a Multilevel Doubly Linked List", "M"),
 ("Greedy", "Assign Cookies", "E"), ("Greedy", "Jump Game", "M"), ("Greedy", "Jump Game II", "M"),
 ("Greedy", "Non-overlapping Intervals", "M"), ("Greedy", "Gas Station", "M"), ("Greedy", "Candy", "H"),
 ("Recursion", "Subsets", "M"), ("Recursion", "Subsets II", "M"), ("Recursion", "Combination Sum", "M"),
 ("Recursion", "Combination Sum II", "M"), ("Recursion", "Permutations", "M"),
 ("Recursion", "Palindrome Partitioning", "M"), ("Recursion", "N-Queens", "H"),
 ("Recursion", "Sudoku Solver", "H"), ("Recursion", "Word Search", "M"),
 ("Binary Search", "Binary Search", "E"), ("Binary Search", "Search in Rotated Sorted Array", "M"),
 ("Binary Search", "Find Minimum in Rotated Sorted Array", "M"), ("Binary Search", "Koko Eating Bananas", "M"),
 ("Binary Search", "Median of Two Sorted Arrays", "H"), ("Binary Search", "Search a 2D Matrix", "M"),
 ("Binary Search", "Split Array Largest Sum", "H"), ("Binary Search", "Aggressive Cows (SPOJ)", "H"),
 ("Heaps", "Kth Largest Element in an Array", "M"), ("Heaps", "Top K Frequent Elements", "M"),
 ("Heaps", "Merge k Sorted Lists", "H"), ("Heaps", "Find Median from Data Stream", "H"),
 ("Stack/Queue", "Valid Parentheses", "E"), ("Stack/Queue", "Min Stack", "M"),
 ("Stack/Queue", "Next Greater Element I", "E"), ("Stack/Queue", "Daily Temperatures", "M"),
 ("Stack/Queue", "Largest Rectangle in Histogram", "H"), ("Stack/Queue", "Sliding Window Maximum", "H"),
 ("Stack/Queue", "LRU Cache", "M"), ("Stack/Queue", "Implement Queue using Stacks", "E"),
 ("Strings", "Longest Palindromic Substring", "M"), ("Strings", "Longest Common Prefix", "E"),
 ("Strings", "Valid Anagram", "E"), ("Strings", "Longest Substring Without Repeating Characters", "M"),
 ("Strings", "Reverse Words in a String", "M"), ("Strings", "Minimum Window Substring", "H"),
 ("Trees", "Binary Tree Inorder Traversal", "E"), ("Trees", "Maximum Depth of Binary Tree", "E"),
 ("Trees", "Diameter of Binary Tree", "E"), ("Trees", "Balanced Binary Tree", "E"),
 ("Trees", "Binary Tree Level Order Traversal", "M"), ("Trees", "Binary Tree Zigzag Level Order Traversal", "M"),
 ("Trees", "Symmetric Tree", "E"), ("Trees", "Lowest Common Ancestor of a Binary Tree", "M"),
 ("Trees", "Validate Binary Search Tree", "M"), ("Trees", "Kth Smallest Element in a BST", "M"),
 ("Trees", "Construct Binary Tree from Preorder and Inorder", "M"), ("Trees", "Binary Tree Maximum Path Sum", "H"),
 ("Trees", "Serialize and Deserialize Binary Tree", "H"), ("Trees", "Flatten Binary Tree to Linked List", "M"),
 ("Graphs", "Number of Islands", "M"), ("Graphs", "Flood Fill", "E"), ("Graphs", "Rotting Oranges", "M"),
 ("Graphs", "Clone Graph", "M"), ("Graphs", "Course Schedule", "M"), ("Graphs", "Course Schedule II", "M"),
 ("Graphs", "Number of Provinces", "M"), ("Graphs", "Network Delay Time", "M"),
 ("Graphs", "Cheapest Flights Within K Stops", "M"), ("Graphs", "Word Ladder", "H"),
 ("Graphs", "Surrounded Regions", "M"), ("Graphs", "Pacific Atlantic Water Flow", "M"),
 ("DP", "Climbing Stairs", "E"), ("DP", "House Robber", "M"), ("DP", "House Robber II", "M"),
 ("DP", "Coin Change", "M"), ("DP", "Longest Increasing Subsequence", "M"), ("DP", "Longest Common Subsequence", "M"),
 ("DP", "Edit Distance", "H"), ("DP", "Partition Equal Subset Sum", "M"), ("DP", "Word Break", "M"),
 ("DP", "Maximal Square", "M"), ("DP", "Unique Paths II", "M"), ("DP", "Minimum Path Sum", "M"),
 ("DP", "Target Sum", "M"), ("DP", "Palindromic Substrings", "M"), ("DP", "Decode Ways", "M"),
 ("DP", "Burst Balloons", "H"), ("DP", "Best Time to Buy and Sell Stock with Cooldown", "M"),
 ("DP", "Regular Expression Matching", "H"),
 ("Tries", "Implement Trie (Prefix Tree)", "M"), ("Tries", "Word Search II", "H"),
 ("Bit Manipulation", "Single Number", "E"), ("Bit Manipulation", "Number of 1 Bits", "E"),
 ("Bit Manipulation", "Counting Bits", "E"),
]


# Your exams (3:00-5:00 pm). Added once; re-running seed never duplicates them.
EXAMS = [
    ("Foundations of Artificial Intelligence and Machine Learning", "2026-12-15"),
    ("Advanced Probability & Statistics", "2026-12-16"),
    ("Fundamentals of Cloud Computing", "2026-12-17"),
    ("Cloud Networking & Security", "2026-12-18"),
    ("Cloud Architecture & Services", "2026-12-21"),
]


def run(csv_path=None):
    db.init()
    for title, day in EXAMS:
        if not db.q("SELECT 1 FROM events WHERE kind='exam' AND title=? AND start=?", (title, day)):
            db.x("INSERT INTO events(kind,title,start,end) VALUES('exam',?,?,?)", (title, day, day))
    # drop unfinished topics that are no longer in the list; keep anything you've marked done
    keep = ",".join("?" * len(JAVA_TOPICS))
    db.x(f"DELETE FROM topics WHERE done=0 AND name NOT IN ({keep})", tuple(JAVA_TOPICS))
    for i, t in enumerate(JAVA_TOPICS):
        db.x("INSERT INTO topics(ord,name) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET ord=excluded.ord",
             (i, t))
    if csv_path:
        with open(csv_path, encoding="utf-8-sig") as f:
            add, tot = import_text(f.read())
        print(f"Imported {add} new problems ({tot} total).")
    else:
        add_problems([(canon_topic(t), n, d) for t, n, d in P], "Striver")
    n = db.q("SELECT COUNT(*) n FROM problems")[0]["n"]
    print(f"Seeded. {len(JAVA_TOPICS)} Java topics, {n} problems total.")


# Problem topic -> course topic you must finish before those problems are suggested.
# Topics not listed here (Basics, Maths, Bit Manipulation...) are always available.
PREREQ = {
    "Arrays": "Arrays (1D and 2D) theory",
    "Strings": "Arrays (1D and 2D) theory",
    "Sorting": "Sorting algorithms",
    "Hashing": "Hashing",
    "Binary Search": "Searching algorithms",
    "Linked List": "Singly Linked List",
    "Stack/Queue": "Stack (array + linked list) + exercises",
    "Recursion": "Recursion",
    "Trees": "Binary Tree (+ iterative traversals)",
    "Heaps": "Binary Heap",
    "Tries": "Trie",
    "Graphs": "Graph traversal: BFS and DFS",
    "DP": "Dynamic Programming: memoization, tabulation",
    "Greedy": "Greedy algorithms",
}

_CANON = [  # (keyword in sheet/module name, canonical topic) - first match wins
    ("binary search tree", "Trees"), ("bst", "Trees"), ("tree", "Trees"),
    ("binary search", "Binary Search"), ("link", "Linked List"),
    ("stack", "Stack/Queue"), ("queue", "Stack/Queue"), ("recurs", "Recursion"),
    ("backtrack", "Recursion"), ("graph", "Graphs"), ("dynamic", "DP"), ("dp", "DP"),
    ("heap", "Heaps"), ("trie", "Tries"), ("bit", "Bit Manipulation"), ("greedy", "Greedy"),
    ("sort", "Sorting"), ("hash", "Hashing"), ("string", "Strings"), ("array", "Arrays"),
    ("sliding", "Arrays"), ("pointer", "Arrays"), ("math", "Maths"),
    ("beginner", "Basics"), ("basic", "Basics"), ("pattern", "Basics"),
]


def canon_topic(name: str) -> str:
    n = name.lower()
    for kw, topic in _CANON:
        if kw in n:
            return topic
    return name.strip() or "Misc"


def add_problems(rows, source):
    base = db.q("SELECT COALESCE(MAX(ord),0)+1 n FROM problems")[0]["n"]
    before = db.q("SELECT COUNT(*) n FROM problems")[0]["n"]
    for i, (topic, name, diff) in enumerate(rows):
        db.x("INSERT OR IGNORE INTO problems(ord,topic,name,difficulty,source) VALUES(?,?,?,?,?)",
             (base + i, topic, name, diff or "M", source))
    after = db.q("SELECT COUNT(*) n FROM problems")[0]["n"]
    return after - before, after


def import_text(text: str, source="Import"):
    """Accepts CSV lines 'topic,name[,difficulty]' OR plain lists where a line ending in ':'
    (or starting with '#') sets the topic and other lines are problem names."""
    import re
    topic, rows = "Misc", []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.endswith(":") or line.startswith("#"):
            topic = canon_topic(line.strip("#: ").strip())
            continue
        if "," in line:
            parts = [p.strip().strip('"') for p in line.split(",")]
            if parts[0].lower() in ("topic", "module", "step"):
                continue
            if len(parts) >= 2 and parts[1]:
                rows.append((canon_topic(parts[0]), parts[1], parts[2] if len(parts) > 2 else "M"))
                continue
        name = re.sub(r"^\s*\d+[\.\)]\s*", "", line)
        rows.append((topic, name, "M"))
    db.init()
    return add_problems(rows, source)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
