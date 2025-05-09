import random

WIDTH, HEIGHT = 40, 20
GENERATIONS = 10

def random_board():
    return [[random.choice([0, 1]) for _ in range(WIDTH)] for _ in range(HEIGHT)]

def step(board):
    def live_neighbors(x, y):
        return sum(
            board[y + dy][(x + dx) % WIDTH]
            for dx in [-1, 0, 1]
            for dy in [-1, 0, 1]
            if not (dx == 0 and dy == 0) and 0 <= y + dy < HEIGHT
        )
    return [
        [1 if (board[y][x] and 2 <= live_neighbors(x, y) <= 3) or (not board[y][x] and live_neighbors(x, y) == 3) else 0
         for x in range(WIDTH)]
        for y in range(HEIGHT)
    ]

def board_to_ascii(board):
    return '\n'.join(''.join('⬛' if cell else '⬜' for cell in row) for row in board)

board = random_board()
for _ in range(GENERATIONS):
    board = step(board)

ascii_output = board_to_ascii(board)

with open("README.md", "r") as f:
    readme = f.read()

start_tag = "<!-- LIFE-START -->"
end_tag = "<!-- LIFE-END -->"

before = readme.split(start_tag)[0]
after = readme.split(end_tag)[1]

with open("README.md", "w") as f:
    f.write(f"{before}{start_tag}\n```\n{ascii_output}\n```\n{end_tag}{after}")
