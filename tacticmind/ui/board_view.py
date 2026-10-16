"""Chessboard: drawing, drag-and-drop and click-click, legal-move dots, promotion, animations,
engine arrows, and arrows and square marks drawn with the right mouse button.

Right button (as on chess.com / lichess):
 - dragging from square to square draws an arrow (L-shaped for a knight move),
 - clicking marks a square,
 - drawing the same arrow / mark again removes it,
 - Shift = red, Ctrl = blue, Alt = teal (amber by default),
 - a left click on the board or making a move clears the drawings.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import chess
import pygame

from . import badges, fonts, gfx, theme
from .anim import ease_in_out_cubic, ease_out_back, ease_out_cubic
from .effects import Effects
from .pieces import piece_surface
from .scale import px
from .widgets import draw_text, icon_check, icon_cross

ANIMATION_TIME = 0.2
Color = tuple[int, ...]
Arrow = tuple[chess.Square, chess.Square]


@dataclass
class _Anim:
    pieces: list[tuple[chess.Piece, chess.Square, chess.Square]]
    captured: tuple[chess.Piece, chess.Square] | None
    start: float
    duration: float
    #: True when undoing a move: the captured piece does not vanish but smoothly returns to the board.
    restore: bool = False


@dataclass
class _Promotion:
    from_square: chess.Square
    to_square: chess.Square
    color: chess.Color


def drawing_color(mods: int) -> Color:
    """Arrow/mark colour depending on the modifier key held."""
    if mods & pygame.KMOD_SHIFT:
        return theme.USER_ARROW_SHIFT
    if mods & pygame.KMOD_CTRL:
        return theme.USER_ARROW_CTRL
    if mods & pygame.KMOD_ALT:
        return theme.USER_ARROW_ALT
    return theme.USER_ARROW


def is_knight_jump(a: chess.Square, b: chess.Square) -> bool:
    df = abs(chess.square_file(a) - chess.square_file(b))
    dr = abs(chess.square_rank(a) - chess.square_rank(b))
    return {df, dr} == {1, 2}


class BoardView:
    def __init__(self) -> None:
        self.rect = pygame.Rect(0, 0, 480, 480)
        self.board = chess.Board()
        self.orientation: chess.Color = chess.WHITE
        self.player_color: chess.Color = chess.WHITE
        self.interactive = False
        self.on_move: Callable[[chess.Move], None] | None = None
        self.last_move: chess.Move | None = None
        self.hint_square: chess.Square | None = None
        #: Engine arrows (from, to, colour).
        self.arrows: list[tuple[chess.Square, chess.Square, Color]] = []
        #: Player drawings (right mouse button).
        self.user_arrows: dict[Arrow, Color] = {}
        self.marks: dict[chess.Square, Color] = {}
        #: Badge on the target square: (square, kind "ok" / "bad" / "brilliant", time it appeared).
        self.feedback: tuple[chess.Square, str, float] | None = None
        self.selected: chess.Square | None = None
        self.selected_at = 0.0
        self.drag_square: chess.Square | None = None
        self.drag_pos: tuple[int, int] = (0, 0)
        #: Where the button was pressed — dragging starts only after leaving the dead zone.
        self.drag_origin: tuple[int, int] = (0, 0)
        self.drag_moved = False
        self.promotion: _Promotion | None = None
        self.anim: _Anim | None = None
        self.hover_pos: tuple[int, int] = (-1, -1)
        self.effects = Effects()
        self._right_start: chess.Square | None = None
        self._right_end: chess.Square | None = None
        self._right_color: Color = theme.USER_ARROW
        self._skip_next_animation = False
        self._shake_at = -10.0
        self._engine_key: tuple[object, ...] = ()
        self._engine_since = 0.0
        self.clock = 0.0
        # Cache: the squares-and-coordinates layer (changes only when size/orientation changes)
        # and a reusable canvas — no new surfaces are created every frame.
        self._base: pygame.Surface | None = None
        self._base_key: tuple[int, bool] = (0, True)
        self._canvas: pygame.Surface | None = None
        self._tints: dict[tuple[int, tuple[int, ...]], pygame.Surface] = {}

    # ------------------------------------------------------------ geometry
    @property
    def square_size(self) -> int:
        return self.rect.width // 8

    def _local_rect(self, square: chess.Square) -> pygame.Rect:
        s = self.square_size
        file, rank = chess.square_file(square), chess.square_rank(square)
        col = file if self.orientation == chess.WHITE else 7 - file
        row = 7 - rank if self.orientation == chess.WHITE else rank
        return pygame.Rect(col * s, row * s, s, s)

    def square_rect(self, square: chess.Square) -> pygame.Rect:
        return self._local_rect(square).move(self.rect.x, self.rect.y)

    def square_at(self, pos: tuple[int, int]) -> chess.Square | None:
        s = self.square_size
        x, y = pos[0] - self.rect.x, pos[1] - self.rect.y
        if not (0 <= x < s * 8 and 0 <= y < s * 8):
            return None
        col, row = x // s, y // s
        file = col if self.orientation == chess.WHITE else 7 - col
        rank = 7 - row if self.orientation == chess.WHITE else row
        return chess.square(file, rank)

    # ------------------------------------------------------------ state
    def set_position(
        self, board: chess.Board, move: chess.Move | None = None, animate: bool = True, undo: chess.Move | None = None
    ) -> None:
        """New position; ``move`` = the move that led to it (highlight and animation).

        ``undo`` = the move being undone (◀): the piece smoothly returns to its start square
        and the captured piece reappears.
        """
        previous = self.board
        self.board = board.copy(stack=False)
        self.last_move = move
        self.selected = None
        self.drag_square = None
        self.promotion = None
        if move is not None or undo is not None:
            self.clear_drawings()
        if undo is not None and animate:
            self.anim = self._undo_animation(previous, self.board, undo)
        elif move is not None and animate and not self._skip_next_animation:
            moving = previous.piece_at(move.from_square)
            if moving is not None:
                shown = chess.Piece(chess.PAWN, moving.color) if move.promotion else moving
                pieces = [(shown, move.from_square, move.to_square)]
                if moving.piece_type == chess.KING and abs(chess.square_file(move.to_square) - chess.square_file(move.from_square)) == 2:
                    rank = chess.square_rank(move.from_square)
                    kingside = chess.square_file(move.to_square) == 6
                    rook_from, rook_to = chess.square(7 if kingside else 0, rank), chess.square(5 if kingside else 3, rank)
                    rook = previous.piece_at(rook_from)
                    if rook is not None:
                        pieces.append((rook, rook_from, rook_to))
                captured_square = move.to_square
                if moving.piece_type == chess.PAWN and previous.ep_square == move.to_square:
                    captured_square = move.to_square + (-8 if moving.color == chess.WHITE else 8)
                victim = previous.piece_at(captured_square)
                captured = (victim, captured_square) if victim is not None and victim.color != moving.color else None
                self.anim = _Anim(pieces, captured, self.clock, ANIMATION_TIME)
        else:
            self.anim = None
        self._skip_next_animation = False

    def _undo_animation(self, after: chess.Board, before: chess.Board, move: chess.Move) -> _Anim | None:
        """Animation undoing ``move``: from position ``after`` back to ``before``."""
        moving = before.piece_at(move.from_square)
        if moving is None or after.piece_at(move.to_square) is None:
            return None
        pieces = [(moving, move.to_square, move.from_square)]
        if before.is_castling(move):
            rank = chess.square_rank(move.from_square)
            kingside = chess.square_file(move.to_square) > chess.square_file(move.from_square)
            rook_home, rook_after = chess.square(7 if kingside else 0, rank), chess.square(5 if kingside else 3, rank)
            rook = before.piece_at(rook_home)
            if rook is not None:
                pieces.append((rook, rook_after, rook_home))
        captured = None
        if before.is_capture(move):
            square = move.to_square
            if before.is_en_passant(move):
                square = move.to_square + (-8 if moving.color == chess.WHITE else 8)
            victim = before.piece_at(square)
            if victim is not None:
                captured = (victim, square)
        return _Anim(pieces, captured, self.clock, ANIMATION_TIME, restore=True)

    def show_feedback(self, square: chess.Square, ok: bool, brilliant: bool = False) -> None:
        """✓ (good move), ✗ (mistake) or !! (brilliant move — a sacrifice) in the corner of the target square."""
        kind = "brilliant" if ok and brilliant else "ok" if ok else "bad"
        self.feedback = (square, kind, self.clock)
        rect = self.square_rect(square)
        center = (rect.right - self.square_size * 0.1, rect.top + self.square_size * 0.1)
        color = {"ok": theme.ACCENT, "bad": theme.RED, "brilliant": theme.BRILLIANT}[kind]
        self.effects.ring(center, self.square_size * 0.3, color)
        if kind == "brilliant":
            # Brilliant move: a second, larger wave and sparks in the "!!" colour.
            self.effects.ring(center, self.square_size * 0.55, theme.BRILLIANT, 0.9)
            self.effects.burst(center, [theme.BRILLIANT, (255, 255, 255), theme.ACCENT], count=22)

    def show_badge(self, square: chess.Square, cls: str, effect: bool = True) -> None:
        """Move-class badge (coach game): !!, !, ★, ✓, book, ?!, ?, ??."""
        self.feedback = (square, f"cls:{cls}", self.clock if effect else self.clock - 1.0)
        if effect:
            rect = self.square_rect(square)
            center = (rect.right - self.square_size * 0.1, rect.top + self.square_size * 0.1)
            color = badges.COLORS.get(cls, theme.MUTED)
            self.effects.ring(center, self.square_size * 0.3, (color[0], color[1], color[2]))
            if cls == "brilliant":
                self.effects.ring(center, self.square_size * 0.55, theme.BRILLIANT, 0.9)
                self.effects.burst(center, [theme.BRILLIANT, (255, 255, 255), theme.ACCENT], count=22)

    def shake(self) -> None:
        """A short board shake after a mistake."""
        self._shake_at = self.clock

    def celebrate(self, square: chess.Square) -> None:
        """Confetti from the square where the puzzle was solved."""
        center = self.square_rect(square).center
        self.effects.burst(center, [theme.ACCENT, theme.VIOLET, theme.AMBER, theme.ROSE, theme.BLUE, (255, 255, 255)])

    def clear_drawings(self) -> None:
        self.user_arrows.clear()
        self.marks.clear()

    def legal_targets(self, square: chess.Square) -> set[chess.Square]:
        return {m.to_square for m in self.board.legal_moves if m.from_square == square}

    def _can_move(self) -> bool:
        return self.interactive and self.board.turn == self.player_color and self.anim is None

    # ------------------------------------------------------------ events
    def handle(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self.hover_pos = event.pos
            if self._right_start is not None:
                self._right_end = self.square_at(event.pos)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            return self._right_down(event.pos)
        if event.type == pygame.MOUSEBUTTONUP and event.button == 3 and self._right_start is not None:
            self._right_up(event.pos)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._left_down(event.pos)
        if event.type == pygame.MOUSEMOTION and self.drag_square is not None:
            buttons = getattr(event, "buttons", (1, 0, 0))
            if not buttons[0]:
                # The button was released outside the window — end the drag, the piece stays selected.
                self.drag_square = None
                self.drag_moved = False
                return True
            self.drag_pos = event.pos
            if not self.drag_moved and math.dist(event.pos, self.drag_origin) > self.drag_deadzone():
                self.drag_moved = True
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.drag_square is not None:
            source = self.drag_square
            self.drag_square = None
            target = self.square_at(event.pos)
            if self.drag_moved and target is not None and target != source and target in self.legal_targets(source):
                self._skip_next_animation = True
                self._attempt(source, target)
            elif self.drag_moved and target != source:
                self.selected = None  # dropped on an illegal square — goes back
            return True
        return False

    def drag_deadzone(self) -> float:
        """Drag dead zone: a slight mouse twitch while clicking does not pick up the piece."""
        return max(px(10), self.square_size * 0.2)

    def _right_down(self, pos: tuple[int, int]) -> bool:
        square = self.square_at(pos)
        self.selected = None
        self.promotion = None
        if square is None:
            return False
        self._right_start = self._right_end = square
        self._right_color = drawing_color(pygame.key.get_mods())
        return True

    def _right_up(self, pos: tuple[int, int]) -> None:
        start, end = self._right_start, self.square_at(pos)
        self._right_start = self._right_end = None
        if start is None or end is None:
            return
        color = self._right_color
        if end == start:
            if self.marks.get(start) == color:
                del self.marks[start]
            else:
                self.marks[start] = color
        elif self.user_arrows.get((start, end)) == color:
            del self.user_arrows[(start, end)]
        else:
            self.user_arrows[(start, end)] = color

    def _left_down(self, pos: tuple[int, int]) -> bool:
        if self.promotion is not None:
            self._click_promotion(pos)
            return True
        square = self.square_at(pos)
        if square is None:
            self.selected = None
            return False
        self.clear_drawings()
        if self.selected is not None and square in self.legal_targets(self.selected) and self._can_move():
            self._attempt(self.selected, square)
            return True
        piece = self.board.piece_at(square)
        if piece is not None and piece.color == self.player_color and self._can_move():
            self.selected = square
            self.selected_at = self.clock
            self.drag_square = square
            self.drag_pos = pos
            self.drag_origin = pos
            self.drag_moved = False
        else:
            self.selected = None
        return True

    def _attempt(self, from_square: chess.Square, to_square: chess.Square) -> None:
        moves = [m for m in self.board.legal_moves if m.from_square == from_square and m.to_square == to_square]
        self.selected = None
        if not moves:
            return
        if any(m.promotion for m in moves):
            self.promotion = _Promotion(from_square, to_square, self.board.turn)
            return
        if self.on_move:
            self.on_move(moves[0])

    def _promotion_squares(self, promotion: _Promotion) -> list[tuple[chess.PieceType, pygame.Rect]]:
        """A column of 4 squares with pieces to choose from, from the promotion square towards the board centre."""
        target = self.square_rect(promotion.to_square)
        s = self.square_size
        downwards = target.y < self.rect.centery
        result = []
        for i, piece_type in enumerate((chess.QUEEN, chess.KNIGHT, chess.ROOK, chess.BISHOP)):
            y = target.y + i * s if downwards else target.y - i * s
            result.append((piece_type, pygame.Rect(target.x, y, s, s)))
        return result

    def _click_promotion(self, pos: tuple[int, int]) -> None:
        promotion = self.promotion
        assert promotion is not None
        self.promotion = None
        for piece_type, rect in self._promotion_squares(promotion):
            if rect.collidepoint(pos):
                move = chess.Move(promotion.from_square, promotion.to_square, promotion=piece_type)
                if move in self.board.legal_moves and self.on_move:
                    self.on_move(move)
                return

    # ------------------------------------------------------------ drawing
    def update(self, dt: float) -> None:
        self.clock += dt
        if self.anim is not None and self.clock - self.anim.start >= self.anim.duration:
            self.anim = None
        self.effects.update(dt)

    def arrow_points(self, from_sq: chess.Square, to_sq: chess.Square) -> list[tuple[float, float]]:
        """Arrow points in board coordinates; a knight move as an L."""
        s = self.square_size
        a = self._local_rect(from_sq).center
        b = self._local_rect(to_sq).center
        if is_knight_jump(from_sq, to_sq):
            dx, dy = b[0] - a[0], b[1] - a[1]
            corner = (b[0], a[1]) if abs(dx) > abs(dy) else (a[0], b[1])
            ang = math.atan2(b[1] - corner[1], b[0] - corner[0])
            end = (b[0] - math.cos(ang) * s * 0.18, b[1] - math.sin(ang) * s * 0.18)
            return [(float(a[0]), float(a[1])), (float(corner[0]), float(corner[1])), end]
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        start = (a[0] + math.cos(ang) * s * 0.12, a[1] + math.sin(ang) * s * 0.12)
        end = (b[0] - math.cos(ang) * s * 0.18, b[1] - math.sin(ang) * s * 0.18)
        return [start, end]

    def draw(self, surface: pygame.Surface) -> None:
        s = self.square_size
        size = (s * 8, s * 8)
        radius = max(4, px(12))
        clock = self.clock
        gfx.shadow(surface, pygame.Rect(self.rect.topleft, size), radius, px(22), 150, (0, px(10)), covered=True)
        # The shake after a mistake moves the whole board horizontally.
        shake_age = clock - self._shake_at
        offset = round(math.sin(shake_age * 48) * px(9) * (1 - shake_age / 0.4)) if shake_age < 0.4 else 0
        target = pygame.Rect((self.rect.x + offset, self.rect.y), size)

        # Draw straight to the screen (no intermediate board-sized canvas — that's two fewer copies of
        # a million pixels per frame at 1440p); the rounded corners are fixed up afterwards on small patches.
        direct = surface.get_clip().contains(target)  # a subsurface does not respect the clip area
        if direct:
            corners = gfx.corner_areas(size, radius)
            behind = [surface.subsurface(area.move(target.topleft)).copy() for area in corners]
            canvas = surface.subsurface(target)
        else:
            if self._canvas is None or self._canvas.get_size() != size:
                self._canvas = pygame.Surface(size, pygame.SRCALPHA)
            canvas = self._canvas
        canvas.blit(self._base_layer(s), (0, 0))
        self._draw_squares(canvas, s, clock)
        self._draw_pieces(canvas, s, clock)
        self._draw_arrows(canvas, s, clock)
        if self.promotion is not None:
            self._draw_promotion(canvas, size)

        if direct:
            mask = gfx.rounded_mask(size, radius)
            for area, under in zip(corners, behind):
                corner = pygame.Surface(area.size, pygame.SRCALPHA)
                corner.blit(canvas, (0, 0), area)
                corner.blit(mask, (0, 0), area, special_flags=pygame.BLEND_RGBA_MULT)
                pos = area.move(target.topleft).topleft
                surface.blit(under, pos)
                surface.blit(corner, pos)
        else:
            gfx.round_corners(canvas, radius)
            surface.blit(canvas, target.topleft)
        gfx.rrect(surface, (255, 255, 255, 20), target, radius, max(1, px(1)))

        self._draw_feedback(surface, s, clock, offset)
        if self.drag_square is not None and self.drag_moved:
            piece = self.board.piece_at(self.drag_square)
            if piece is not None:
                img = piece_surface(piece, int(s * 1.12))
                ghost = img.copy()
                ghost.fill((0, 0, 0, 90), special_flags=pygame.BLEND_RGBA_MULT)
                surface.blit(ghost, ghost.get_rect(center=(self.drag_pos[0] + px(4), self.drag_pos[1] + px(8))))
                surface.blit(img, img.get_rect(center=self.drag_pos))
        self.effects.draw(surface)

    def _base_layer(self, s: int) -> pygame.Surface:
        """Squares and coordinates — drawn once per board size and orientation."""
        key = (s, self.orientation == chess.WHITE)
        if self._base is not None and self._base_key == key:
            return self._base
        base = pygame.Surface((s * 8, s * 8), pygame.SRCALPHA)
        for square in chess.SQUARES:
            light = (chess.square_file(square) + chess.square_rank(square)) % 2 == 1
            pygame.draw.rect(base, theme.BOARD_LIGHT if light else theme.BOARD_DARK, self._local_rect(square))
        label_size = max(9, s // 6)
        margin = max(2, s // 20)
        for i in range(8):
            for square, corner in (
                (chess.square(i, 0 if self.orientation == chess.WHITE else 7), "file"),
                (chess.square(0 if self.orientation == chess.WHITE else 7, i), "rank"),
            ):
                r = self._local_rect(square)
                light = (chess.square_file(square) + chess.square_rank(square)) % 2 == 1
                color = theme.COORD_ON_LIGHT if light else theme.COORD_ON_DARK
                if corner == "file":
                    surf = fonts.render("abcdefgh"[i], label_size, color, "bold")
                    base.blit(surf, (r.right - surf.get_width() - margin, r.bottom - surf.get_height()))
                else:
                    surf = fonts.render(str(i + 1), label_size, color, "bold")
                    base.blit(surf, (r.x + margin, r.y + 1))
        self._base, self._base_key = base, key
        return base

    def _tint(self, canvas: pygame.Surface, square: chess.Square, color: tuple[int, ...]) -> None:
        """Semi-transparent square highlight (a ready surface from the cache)."""
        s = self.square_size
        surf = self._tints.get((s, color))
        if surf is None:
            surf = pygame.Surface((s, s), pygame.SRCALPHA)
            surf.fill(color)
            self._tints[(s, color)] = surf
        canvas.blit(surf, self._local_rect(square))

    def _draw_squares(self, canvas: pygame.Surface, s: int, clock: float) -> None:
        if self.last_move is not None:
            for sq in (self.last_move.from_square, self.last_move.to_square):
                self._tint(canvas, sq, theme.LAST_MOVE)
        if self.selected is not None:
            self._tint(canvas, self.selected, theme.SELECTED)
        for square, color in self.marks.items():
            r = self._local_rect(square).inflate(-px(4), -px(4))
            gfx.rrect(canvas, (*color[:3], 120), r, px(8))
            gfx.rrect(canvas, (*color[:3], 230), r, px(8), max(2, px(3)))
        # Hint: a pulsing violet ring; check: a red glow.
        if self.hint_square is not None:
            pulse = 0.5 + 0.5 * math.sin(clock * 5)
            c = self._local_rect(self.hint_square).center
            gfx.ring_glow(canvas, theme.VIOLET, c, s * (0.75 + 0.08 * pulse), int(150 + 60 * pulse))
            gfx.circle(canvas, (*theme.VIOLET[:3], 230), c, s * (0.44 + 0.03 * pulse), max(2, px(3)))
        if self.board.is_check():
            king = self.board.king(self.board.turn)
            if king is not None:
                pulse = 0.5 + 0.5 * math.sin(clock * 6)
                gfx.ring_glow(canvas, theme.CHECK, self._local_rect(king).center, s * 0.78, int(170 + 60 * pulse))

    def _draw_pieces(self, canvas: pygame.Surface, s: int, clock: float) -> None:
        hidden: set[chess.Square] = set()
        anim = self.anim
        progress = ease_in_out_cubic((clock - anim.start) / anim.duration) if anim is not None else 1.0
        if anim is not None:
            hidden = {to for _, _, to in anim.pieces}
            if anim.restore and anim.captured is not None:
                hidden.add(anim.captured[1])  # the returning piece is drawn underneath, fading in
        if self.drag_square is not None and self.drag_moved:
            hidden.add(self.drag_square)
        for square, piece in self.board.piece_map().items():
            if square not in hidden:
                img = piece_surface(piece, s)
                canvas.blit(img, img.get_rect(center=self._local_rect(square).center))
        # Legal-move dots (fade in smoothly)
        if self.selected is not None and self._can_move():
            appear = ease_out_back((clock - self.selected_at) / 0.22)
            for target in self.legal_targets(self.selected):
                c = self._local_rect(target).center
                if self.board.piece_at(target) is not None:
                    gfx.circle(canvas, theme.DOT, c, s * 0.46, max(3, int(s * 0.08)))
                else:
                    gfx.circle(canvas, theme.DOT, c, max(1.0, s * 0.16 * appear))
        # Move animation: the captured piece fades out, the moving one slides smoothly
        if anim is not None:
            if anim.captured is not None:
                victim, square = anim.captured
                img = piece_surface(victim, s).copy()
                fade = ease_out_cubic(progress * 1.4)
                img.set_alpha(int(255 * (fade if anim.restore else 1 - fade)))
                canvas.blit(img, img.get_rect(center=self._local_rect(square).center))
            for piece, from_sq, to_sq in anim.pieces:
                a = self._local_rect(from_sq).center
                b = self._local_rect(to_sq).center
                pos = (a[0] + (b[0] - a[0]) * progress, a[1] + (b[1] - a[1]) * progress)
                img = piece_surface(piece, s)
                canvas.blit(img, img.get_rect(center=(round(pos[0]), round(pos[1]))))

    def _draw_arrows(self, canvas: pygame.Surface, s: int, clock: float) -> None:
        engine_key = tuple((f, to) for f, to, _ in self.arrows)  # a colour change does not restart the animation
        if engine_key != self._engine_key:
            self._engine_key = engine_key
            self._engine_since = clock
        if self.arrows:
            engine = [
                (self.arrow_points(f, t), color, s * (0.2 if i == len(self.arrows) - 1 else 0.16))
                for i, (f, t, color) in enumerate(reversed(self.arrows))
            ]
            gfx.draw_arrows(canvas, engine, ease_out_cubic((clock - self._engine_since) / 0.35))
        drawings = [(self.arrow_points(f, t), color, s * 0.18) for (f, t), color in self.user_arrows.items()]
        if self._right_start is not None and self._right_end is not None and self._right_end != self._right_start:
            drawings.append((self.arrow_points(self._right_start, self._right_end), (*self._right_color[:3], 140), s * 0.18))
        if drawings:
            gfx.draw_arrows(canvas, drawings)

    def _draw_promotion(self, canvas: pygame.Surface, size: tuple[int, int]) -> None:
        promotion = self.promotion
        assert promotion is not None
        shade = pygame.Surface(size, pygame.SRCALPHA)
        shade.fill((8, 10, 18, 150))
        canvas.blit(shade, (0, 0))
        column = self._promotion_squares(promotion)
        box = column[0][1].unionall([r for _, r in column]).move(-self.rect.x, -self.rect.y)
        gfx.rrect(canvas, theme.SURFACE_2, box, px(10))
        gfx.rrect(canvas, theme.BORDER, box, px(10), max(1, px(1)))
        for piece_type, rect in column:
            local = rect.move(-self.rect.x, -self.rect.y)
            if rect.collidepoint(self.hover_pos):
                gfx.rrect(canvas, (*theme.ACCENT[:3], 60), local.inflate(-px(6), -px(6)), px(8))
            img = piece_surface(chess.Piece(piece_type, promotion.color), self.square_size)
            canvas.blit(img, img.get_rect(center=local.center))

    def _draw_feedback(self, surface: pygame.Surface, s: int, clock: float, offset: int) -> None:
        """✓ / ✗ in the corner of the target square (pops in with a springy effect)."""
        if self.feedback is None:
            return
        square, kind, started = self.feedback
        pop = ease_out_back((clock - started) / 0.3, 2.2)
        rect = self.square_rect(square).move(offset, 0)
        radius = max(px(9), s * 0.19) * pop
        if radius <= 1:
            return
        center = (rect.right - s * 0.1, rect.top + s * 0.1)
        if kind.startswith("cls:"):
            badges.draw_badge(surface, center, max(px(9), s * 0.19), kind[4:], pop)
            return
        gfx.circle(surface, (*theme.SHADOW, 120), (center[0], center[1] + px(2)), radius + px(2))
        if kind == "brilliant":
            # "!!" — pulses slightly so it stands out from a plain ✓.
            glow = 0.5 + 0.5 * math.sin((clock - started) * 6)
            gfx.ring_glow(surface, theme.BRILLIANT, center, radius * (2.4 + 0.3 * glow), int(120 + 60 * glow))
            gfx.circle(surface, theme.BRILLIANT, center, radius * 1.12)
            draw_text(surface, "!!", (center[0], center[1] - radius * 0.06), max(9, round(radius * 1.25)), (255, 255, 255), "bold", "center")
            return
        gfx.circle(surface, theme.ACCENT if kind == "ok" else theme.RED, center, radius)
        if kind == "ok":
            icon_check(surface, center, radius * 1.6, (8, 28, 34))
        else:
            icon_cross(surface, center, radius * 1.6, (255, 255, 255))
