"""
Interactive school selection with region filter and incremental keyword filtering.
"""

from data_manager import get_schools, SUPPORTED_REGIONS


def select_region() -> str:
    """
    Interactively ask the user to choose a region.
    Returns a key from SUPPORTED_REGIONS.
    """
    regions = list(SUPPORTED_REGIONS.keys())

    print("\nRegion Selection")
    for i, name in enumerate(regions, 1):
        print(f"  {i}. {name}")
    print()

    while True:
        choice = input("  Select region (number): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(regions):
                selected = regions[idx]
                print(f"\n  Region: {selected}\n")
                return selected
        print(f"  Please enter a number between 1 and {len(regions)}.")


def select_school(region: str | None = None) -> tuple[str, str]:
    """
    Interactively ask the user to choose a school within *region*.
    If region is None, prompts for region selection first.
    Returns (school_name, region) — school name as it appears in CSRankings.
    """
    if region is None:
        region = select_region()

    all_schools = get_schools(region)

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
                return matches[0], region
            continue

        choice = input("  Enter number to select, or type a new keyword to filter: ").strip()

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(matches):
                selected = matches[idx]
                print(f"\n  Selected: {selected}\n")
                return selected, region
            else:
                print(f"  Number out of range (1-{len(matches)}). Try again.\n")
        else:
            keyword = choice.lower()
            matches = [s for s in all_schools if keyword in s.lower()]
            if not matches:
                print(f"  No schools matching '{choice}'.\n")
