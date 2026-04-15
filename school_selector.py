"""
Interactive school selection with incremental keyword filtering.
"""

from data_manager import get_schools


def select_school() -> str:
    """
    Interactively ask the user to choose a school.
    Returns the exact school name as it appears in CSRankings.
    """
    all_schools = get_schools()

    print("\nSchool Selection")
    print("  Type a keyword to filter, then enter the number to select.")
    print("  Examples: 'stanford', 'MIT', 'Carnegie', 'Berkeley'\n")

    matches: list[str] = []

    while True:
        keyword = input("Search school (Enter to list all): ").strip().lower()

        matches = [s for s in all_schools if keyword in s.lower()] if keyword else list(all_schools)

        if not matches:
            print(f"  No schools matching '{keyword}'. Try again.\n")
            continue

        print(f"\n  {len(matches)} school(s) found:\n")
        for i, school in enumerate(matches, 1):
            print(f"  {i:3d}. {school}")
        print()

        if len(matches) == 1:
            choice = input(f"  Press Enter to confirm [{matches[0]}], or search again: ").strip()
            if not choice:
                return matches[0]
            continue

        choice = input("  Enter number to select, or type a new keyword to filter: ").strip()

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(matches):
                selected = matches[idx]
                print(f"\n  Selected: {selected}\n")
                return selected
            else:
                print(f"  Number out of range (1-{len(matches)}). Try again.\n")
        else:
            keyword = choice.lower()
            matches = [s for s in all_schools if keyword in s.lower()]
            if not matches:
                print(f"  No schools matching '{choice}'.\n")
