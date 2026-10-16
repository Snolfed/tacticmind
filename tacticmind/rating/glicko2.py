"""Glicko-2 (Mark Glickman, 2013): a rating with deviation (RD) and volatility (σ).

Unlike Elo, every player also has a rating uncertainty RD. A large RD (new
player) = large changes after every puzzle; RD shrinks as the system "gets to know" the player.
That is why we show an uncertainty interval, e.g. "1450 ± 80".

Algorithm (steps from the paper "Example of the Glicko-2 system"):
 1. convert to the Glicko-2 scale: μ = (r − 1500)/173.7178, φ = RD/173.7178,
 2. variance v and improvement Δ from the period's results,
 3. new volatility σ' — the root of f(x) = 0 using the Illinois method,
 4. φ* = √(φ² + σ'²), φ' = 1/√(1/φ*² + 1/v), μ' = μ + φ'² Σ g(φ_j)(s_j − E_j),
 5. convert back to the rating scale.

One puzzle = one rating period with a single "match" against the puzzle
(the puzzle's rating and RD come from the Lichess database). The score ``s`` may be fractional.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SCALE = 173.7178
TAU = 0.5  # constrains volatility changes
EPSILON = 1e-6


@dataclass(frozen=True)
class Glicko2Rating:
    rating: float = 1200.0
    rd: float = 350.0
    volatility: float = 0.06


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _expected(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def expected_score(player: Glicko2Rating, opponent_rating: float, opponent_rd: float) -> float:
    """Chance of success taking the opponent's rating uncertainty into account."""
    return _expected((player.rating - 1500) / SCALE, (opponent_rating - 1500) / SCALE, opponent_rd / SCALE)


def update(player: Glicko2Rating, results: list[tuple[float, float, float]], tau: float = TAU) -> Glicko2Rating:
    """New rating after a period with results ``(opponent_rating, opponent_rd, score)``."""
    mu = (player.rating - 1500.0) / SCALE
    phi = player.rd / SCALE
    sigma = player.volatility

    if not results:
        # A period without games: only the uncertainty grows.
        phi_star = math.sqrt(phi * phi + sigma * sigma)
        return Glicko2Rating(player.rating, phi_star * SCALE, sigma)

    # Steps 3–4: variance v and improvement Δ.
    v_inv = 0.0
    delta_sum = 0.0
    for opp_rating, opp_rd, score in results:
        mu_j = (opp_rating - 1500.0) / SCALE
        phi_j = opp_rd / SCALE
        g = _g(phi_j)
        e = _expected(mu, mu_j, phi_j)
        v_inv += g * g * e * (1.0 - e)
        delta_sum += g * (score - e)
    v = 1.0 / v_inv
    delta = v * delta_sum

    # Step 5: new volatility (Illinois method on f(x) = 0).
    a = math.log(sigma * sigma)

    def f(x: float) -> float:
        ex = math.exp(x)
        num = ex * (delta * delta - phi * phi - v - ex)
        den = 2.0 * (phi * phi + v + ex) ** 2
        return num / den - (x - a) / (tau * tau)

    big_a = a
    if delta * delta > phi * phi + v:
        big_b = math.log(delta * delta - phi * phi - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        big_b = a - k * tau
    f_a = f(big_a)
    f_b = f(big_b)
    while abs(big_b - big_a) > EPSILON:
        big_c = big_a + (big_a - big_b) * f_a / (f_b - f_a)
        f_c = f(big_c)
        if f_c * f_b <= 0:
            big_a, f_a = big_b, f_b
        else:
            f_a /= 2.0
        big_b, f_b = big_c, f_c
    new_sigma = math.exp(big_a / 2.0)

    # Steps 6–7: new φ and μ.
    phi_star = math.sqrt(phi * phi + new_sigma * new_sigma)
    new_phi = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)
    new_mu = mu + new_phi * new_phi * delta_sum

    return Glicko2Rating(new_mu * SCALE + 1500.0, new_phi * SCALE, new_sigma)
