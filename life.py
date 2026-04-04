import random
import re

WIDTH, HEIGHT = 40, 20
GENERATIONS = 5
STAGNATION_HISTORY = 6  # Check last N boards for cycles

ALIVE = '🟩'
DEAD = '⬛'


def random_board():
    return [[random.choice([0, 1]) for _ in range(WIDTH)] for _ in range(HEIGHT)]


def step(board):
    def live_neighbors(x, y):
        return sum(
            board[(y + dy) % HEIGHT][(x + dx) % WIDTH]
            for dx in [-1, 0, 1]
            for dy in [-1, 0, 1]
            if not (dx == 0 and dy == 0)
        )
    return [
        [
            1 if (board[y][x] and 2 <= live_neighbors(x, y) <= 3)
            or (not board[y][x] and live_neighbors(x, y) == 3)
            else 0
            for x in range(WIDTH)
        ]
        for y in range(HEIGHT)
    ]


def board_to_str(board):
    return '\n'.join(''.join(ALIVE if cell else DEAD for cell in row) for row in board)


def board_key(board):
    return tuple(tuple(row) for row in board)


def parse_board_from_readme(readme):
    """Try to parse the current board state from README."""
    match = re.search(r'<!-- LIFE-START -->\n```\n(.*?)\n```\n<!-- LIFE-END -->', readme, re.DOTALL)
    if not match:
        return None
    grid_text = match.group(1)
    rows = grid_text.strip().split('\n')
    board = []
    for row in rows:
        cells = []
        i = 0
        while i < len(row):
            char = row[i]
            # Emoji can be multi-byte; check for known cell characters
            if row[i:i+len(ALIVE)] == ALIVE:
                cells.append(1)
                i += len(ALIVE)
            elif row[i:i+len(DEAD)] == DEAD:
                cells.append(0)
                i += len(DEAD)
            elif row[i:i+len('⬛')] == '⬛':
                cells.append(1)
                i += len('⬛')
            elif row[i:i+len('⬜')] == '⬜':
                cells.append(0)
                i += len('⬜')
            else:
                i += 1
        if len(cells) == WIDTH:
            board.append(cells)
    if len(board) == HEIGHT:
        return board
    return None


def detect_stagnation(history):
    """Detect if the board has stagnated (still life or short-period oscillator)."""
    if len(history) < 2:
        return False
    current = history[-1]
    # Check if current matches any previous state in history (cycle detection)
    for prev in history[:-1]:
        if prev == current:
            return True
    return False


def population(board):
    return sum(sum(row) for row in board)


# Read current README
with open("README.md", "r") as f:
    readme = f.read()

# Try to continue from existing board state
board = parse_board_from_readme(readme)

# Parse generation counter if present
gen_match = re.search(r'Generation:\s*\*\*(\d+)\*\*', readme)
gen_count = int(gen_match.group(1)) if gen_match else 0

if board is None:
    board = random_board()
    gen_count = 0

# Run generations with stagnation detection
history = [board_key(board)]
stagnated = False

for i in range(GENERATIONS):
    board = step(board)
    key = board_key(board)
    history.append(key)

    # Keep history bounded
    if len(history) > STAGNATION_HISTORY:
        history = history[-STAGNATION_HISTORY:]

    if detect_stagnation(history):
        stagnated = True
        break

    # Also reset if population died out
    if population(board) == 0:
        stagnated = True
        break

gen_count += (GENERATIONS if not stagnated else i + 1)

# Reset if stagnated
if stagnated:
    board = random_board()
    # Run a few generations so the random soup settles into something interesting
    for _ in range(3):
        board = step(board)
    gen_count = 3

ascii_output = board_to_str(board)

# Build the life section
life_section = f"<!-- LIFE-START -->\n```\n{ascii_output}\n```\n\nGeneration: **{gen_count}** | Population: **{population(board)}**/{WIDTH * HEIGHT}\n<!-- LIFE-END -->"

start_tag = "<!-- LIFE-START -->"
end_tag = "<!-- LIFE-END -->"

before = readme.split(start_tag)[0]
after = readme.split(end_tag)[1]

with open("README.md", "w") as f:
    f.write(f"{before}{life_section}{after}")
