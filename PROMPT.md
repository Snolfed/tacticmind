# TaktykAI — szachowe zadania z AI, które myśli na głos

## Kontekst

Tworzysz projekt zaliczeniowy z programowania: grę, która wykorzystuje algorytm sztucznej inteligencji. Gra to trener taktyki szachowej w stylu „Puzzles” z chess.com. Wyróżniają ją dwie rzeczy:

1. **Własny silnik szachowy (AI)**, którego „myśli” widać na żywo w panelu obok szachownicy.
2. **Adaptacyjny poziom trudności**: gra liczy ranking ELO gracza na podstawie jego rozwiązań i dobiera kolejne zadania pod jego aktualny poziom.

**Najważniejsze kryterium oceny:** algorytm AI ma być **napisany od zera w tym projekcie**. Stockfish ani żaden inny gotowy silnik nie może być „mózgiem” gry. Algorytm ma być dobrze widoczny w działaniu i łatwy do wytłumaczenia na obronie projektu. Kod ma być czytelny, z komentarzami w kluczowych miejscach, a algorytmy mają być opisane w README.

## Stack technologiczny

- Vite + React + TypeScript (tryb strict) + Tailwind CSS
- Szachownica: `react-chessboard` (przeciąganie oraz klik-klik)
- `chess.js` **tylko w warstwie UI** (walidacja ruchów gracza, notacja SAN, FEN). Silnik AI ma własną reprezentację planszy i własny generator ruchów.
- Silnik działa w **Web Workerze**, żeby interfejs nigdy się nie przycinał
- Wykresy: Recharts
- Testy: Vitest
- Zapis postępów: localStorage. Bez backendu, wszystko działa offline po `npm run dev`.
- Cały interfejs po polsku

## 1. Silnik AI (serce projektu): `src/engine/`

Zaimplementuj od zera:

- **Reprezentacja planszy** 0x88 (albo mailbox 10x12). Stan: strona na ruchu, prawa do roszady, pole en passant, licznik półruchów. Parsowanie i generowanie FEN.
- **Generator ruchów** z pełnymi zasadami: roszady, bicie w przelocie, promocje na wszystkie 4 figury, wykrywanie szacha, mata i pata, make/unmake move.
- **Perft** do weryfikacji generatora (testy poniżej muszą przechodzić).
- **Wyszukiwanie:**
  - negamax z cięciami alfa-beta,
  - iterative deepening z limitem czasu i głębokości,
  - quiescence search (bicia), żeby uniknąć efektu horyzontu,
  - porządkowanie ruchów: najpierw ruch z PV, potem bicia wg MVV-LVA, killer moves, history heuristic,
  - tablica transpozycji z haszowaniem Zobrista,
  - wyniki matowe z odległością do mata (szybszy mat jest lepszy).
- **Funkcja oceny:** materiał + tablice pozycyjne (piece-square tables) w wersji tapered (osobne wartości dla gry środkowej i końcówki), bonus za bezpieczeństwo króla i mobilność. Ocena w UI zawsze pokazywana z perspektywy białych, w pionach (np. +1.5) albo jako mat (M3).
- **MultiPV:** liczenie 3 najlepszych ruchów kandydujących razem z ich wariantami.
- **Statystyki wyszukiwania** zbierane na bieżąco: głębokość, liczba węzłów, węzły/s, liczba cięć alfa-beta, trafienia w TT, czas, główny wariant (PV).
- **Protokół workera:** po każdej ukończonej głębokości worker wysyła do UI wiadomość `{ depth, scoreCp | mateIn, pv, multiPv, nodes, nps, cutoffs, ttHits, timeMs }`. Obsługuje komendę `stop` i nowe zapytania bez restartu workera.
- **Tryb porównawczy** (na obronę): ta sama pozycja policzona czystym minimaksem i alfa-betą na tej samej głębokości, z wynikiem, ile węzłów zaoszczędzono.

## 2. Panel „Mózg AI”: co AI myśli

Panel jest po prawej stronie szachownicy, a na telefonie pod nią. Zawiera:

- **Pasek oceny** (eval bar) przy szachownicy, jak na chess.com. Animowany, z wartością typu +1.5 albo M3.
- **3 najlepsze ruchy kandydujące** z oceną i wariantem w SAN, np. `1. Hxf7+ Kxf7 2. Sg5+ Kg8 3. Sxe6`. Kliknięcie wariantu odtwarza go na szachownicy w trybie podglądu.
- **Strzałki** na szachownicy: najlepszy ruch na zielono, drugi i trzeci półprzezroczyste.
- **Liczniki na żywo:** głębokość, węzły, węzły/s, odcięte gałęzie, czas.
- **„Strumień myśli”:** log zdań po polsku generowanych z danych wyszukiwania przez szablony, bez zewnętrznego LLM. Przykłady:
  - „Głębokość 4: najlepsze wydaje się Hxf7+ (+3.2). Po Kxf7 Sg5+ wygrywam hetmana.”
  - „Zmieniam zdanie! Na głębokości 6 widzę mata w 3 po Wd8+.”
  - „Dzięki alfa-beta pomijam 84% gałęzi.”

  Każdą zmianę najlepszego ruchu między głębokościami wyraźnie zaznacz. To pokazuje, że AI naprawdę „myśli”.
- **Mini drzewo przeszukiwania** (bonus): pierwsze 2 poziomy drzewa z ocenami. Gałęzie odcięte przez alfa-betę są wyszarzone albo przekreślone.
- **Tryby widoczności**, żeby panel nie zdradzał rozwiązania:
  - *Ukryty*: w trakcie rozwiązywania widać tylko statystyki i to, że AI liczy. Ruchy i ocena są ukryte.
  - *Podpowiedź*: przycisk podświetla figurę, którą trzeba ruszyć. Zmniejsza nagrodę rankingową.
  - *Pełny*: po rozwiązaniu albo porażce widać wszystko, a AI tłumaczy zadanie.

## 3. Zadania szachowe

- Źródło: **baza zadań Lichess** (licencja CC0): https://database.lichess.org/lichess_db_puzzle.csv.zst
  Kolumny: `PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags`.
- Skrypt `scripts/build-puzzles.ts` wybiera z pobranego CSV około 3000 zadań, równomiernie rozłożonych w przedziale 600–2800 (koszyki co 100 punktów). Bierze tylko zadania z `Popularity > 80` i `NbPlays > 500` i zapisuje je do `src/data/puzzles.json`.
- Do repozytorium dołącz mały zestaw startowy (około 50 prawdziwych zadań z bazy Lichess, z różnymi rankingami i motywami), żeby aplikacja działała bez pobierania całej bazy.
- **Uwaga na format Lichess:** `FEN` to pozycja **przed** ruchem przeciwnika. Pierwszy ruch z `Moves` wykonuje przeciwnik (z animacją), dopiero potem gracz zaczyna rozwiązywać. Ruchy są zapisane w UCI. Gracz gra stroną, która jest na ruchu po tym pierwszym ruchu, więc obróć szachownicę na jego stronę.
- Odpowiedzi przeciwnika w trakcie zadania wykonuj automatycznie, z opóźnieniem około 400 ms.
- **Alternatywne rozwiązania:**
  - jeśli ruch gracza różni się od wzorcowego, ale daje mata, zadanie jest rozwiązane,
  - jeśli według silnika ruch nadal wyraźnie wygrywa (np. ocena > +3 i najwyżej 50 cp gorsza od najlepszej), pokaż „Dobry ruch, ale jest lepszy. Spróbuj jeszcze raz” i nie licz tego jako błędu.
- **Motywy** przetłumacz na polski i pokazuj po rozwiązaniu: fork → widełki, pin → związanie, skewer → przeszycie, discoveredAttack → odsłona, sacrifice → poświęcenie, deflection → odciągnięcie, attraction → przyciąganie, backRankMate → mat na ostatniej linii, hangingPiece → wisząca figura, mateIn1/2/3 → mat w 1/2/3, endgame → końcówka itd.
- **Po błędnym ruchu** AI pokazuje odpowiedź przeciwnika wyliczoną przez silnik, np. „Po Wd1? przeciwnik gra Hxh2#. Mat.” Potem gracz może wybrać „Spróbuj ponownie” albo „Pokaż rozwiązanie”.

## 4. Adaptacyjny ranking ELO i dobór zadań

### Ranking gracza

- Start: 1200. Przez pierwsze 10 zadań trwa kalibracja z wysokim współczynnikiem K (np. 60). Potem K spada do 32, a po 50 zadaniach do 20.
- Oczekiwany wynik: `E = 1 / (1 + 10^((R_zadania − R_gracza) / 400))`
- Zmiana rankingu: `ΔR = K · (S − E)`
- Wynik `S` nie jest zero-jedynkowy:
  - 1.0: rozwiązane bez błędu i bez podpowiedzi,
  - 0.5: rozwiązane z podpowiedzią,
  - 0.0: błędny ruch (nawet jeśli gracz potem dokończy zadanie),
  - lekka kara za bardzo długi czas (powyżej 3× przeciętnego czasu gracza), maksymalnie −0.2.
- Bonus: zamiast Elo zaimplementuj Glicko-2 z odchyleniem rankingu (RD) i pokazuj przedział niepewności, np. „1450 ± 80”.

### Dobór kolejnego zadania (drugi element AI: model gracza)

- Celuj w około 65% szans na sukces („strefa flow”): docelowy ranking zadania ≈ `R_gracza − 100`, z losowym rozrzutem ±75.
- **Model gracza** śledzi skuteczność w każdym motywie (widełki, związania, maty…). Około 30% zadań pochodzi z najsłabszych motywów gracza.
- **Ochrona przed frustracją:** po 3 porażkach z rzędu kolejne zadanie jest wyraźnie łatwiejsze. Po 5 sukcesach z rzędu pojawia się „zadanie bonusowe” trudniejsze o około 200.
- Zadania się nie powtarzają, a motywy są zróżnicowane.
- Każdą decyzję o doborze zadania pokaż w okienku „Dlaczego to zadanie?”, np. „Ranking zadania 1380, celuję w 65% szans. Twoja słaba strona: związania (41%)”.

### Prezentacja rankingu

- Duży ranking na górze ekranu z animowaną zmianą po każdym zadaniu (+12 na zielono, −9 na czerwono).
- Ranking zadania widoczny po jego zakończeniu (jak na chess.com).
- Seria (streak) z ikoną ognia.

## 5. UI/UX w stylu chess.com

- Ciemny motyw (tło `#312e2b`), klasyczna zielona szachownica (`#769656` / `#eeeed2`), podświetlenie ostatniego ruchu, kropki na polach legalnych ruchów, okno wyboru figury przy promocji.
- Animacje ruchów i dźwięki (ruch, bicie, szach, sukces, błąd). Dźwięki generowane przez Web Audio API albo pliki z licencją, która pozwala ich użyć.
- Informacja zwrotna: zielony ✓ albo czerwony ✗ na polu docelowym ruchu oraz komunikaty „Najlepszy ruch!” i „Niestety, to nie to”.
- Przyciski: Podpowiedź, Pokaż rozwiązanie, Spróbuj ponownie, Następne zadanie oraz przełącznik trybu panelu AI.
- Ekran statystyk: wykres rankingu w czasie, skuteczność w każdym motywie (wykres radarowy albo słupkowy), liczba zadań, najlepsza seria, średni czas.
- Responsywność: na desktopie szachownica z panelem obok; na telefonie panel pod szachownicą, a poziomy pasek oceny nad nią.
- Ekran startowy z nazwą gry i przyciskami „Graj”, „Statystyki” oraz „Jak działa AI?”. Ta ostatnia strona tłumaczy algorytmy dla prowadzącego i zawiera interaktywne porównanie minimaksu z alfa-betą.

## Architektura

```
src/
  engine/    # własny silnik: board.ts, movegen.ts, eval.ts, search.ts, zobrist.ts, tt.ts, worker.ts
  rating/    # elo.ts (albo glicko2.ts), selector.ts, playerModel.ts
  puzzles/   # loader.ts, themes.ts (tłumaczenia), validator.ts
  ui/        # Board, EvalBar, AIBrainPanel, ThoughtStream, SearchTree, RatingBadge, StatsPage…
  hooks/     # useEngine.ts (komunikacja z workerem), usePuzzleSession.ts
  data/      # puzzles.json
scripts/build-puzzles.ts
tests/
```

Logika gry i silnik są oddzielone od komponentów React: czyste funkcje, łatwe do testowania.

## Testy (Vitest): muszą przechodzić

- Perft z pozycji startowej, głębokości 1–4: 20, 400, 8 902, 197 281.
- Perft „Kiwipete” `r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1`, głębokości 1–3: 48, 2 039, 97 862.
- Perft „pozycja 3” `8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1`, głębokości 1–4: 14, 191, 2 812, 43 238.
- Silnik znajduje mata w 1, 2 i 3 w kilku znanych pozycjach.
- Na małej głębokości alfa-beta zwraca ten sam wynik co czysty minimaks, ale odwiedza mniej węzłów.
- Elo: poprawne E i ΔR dla przykładowych wartości. Selektor zadań trafia w docelowy przedział rankingu.

## Etapy pracy

Pracuj etapami. Po każdym etapie aplikacja musi się uruchamiać (`npm run dev`), a testy przechodzić. Na koniec każdego etapu krótko podsumuj, co zrobiłeś.

1. Szkielet projektu, szachownica, wczytanie zestawu startowego, rozwiązywanie zadań (jeszcze bez AI i rankingu).
2. Silnik: plansza, generator ruchów, testy perft.
3. Wyszukiwanie, funkcja oceny, worker, testy matów.
4. Panel „Mózg AI”: eval bar, strzałki, strumień myśli, tryby widoczności.
5. Ranking Elo, model gracza, dobór zadań, okienko „Dlaczego to zadanie?”.
6. Statystyki, ekran startowy, strona „Jak działa AI?”, dźwięki, animacje, responsywność.
7. Skrypt `build-puzzles.ts` i README.

## README: dokumentacja na obronę

README po polsku zawiera:

- opis gry i instrukcję uruchomienia,
- opis algorytmów: minimaks, alfa-beta (z pseudokodem), iterative deepening, quiescence search, tablica transpozycji, funkcja oceny, Elo/Glicko, dobór zadań,
- diagram architektury (Mermaid),
- tabelę z pomiarami: liczba węzłów dla minimaksu, alfa-bety i alfa-bety z porządkowaniem ruchów na głębokościach 1–5,
- sekcję „Decyzje projektowe”,
- źródła (baza zadań Lichess, CC0).

## Zasady

- Żadnych placeholderów ani „TODO: zaimplementuj”. Każda funkcja ma działać.
- TypeScript strict, bez `any`.
- Nie używaj Stockfisha ani żadnego innego gotowego silnika do liczenia ruchów AI.
- Jeśli coś jest niejasne albo musisz wybrać jedno z dwóch podejść, wybierz rozsądniejsze, zapisz decyzję w README w sekcji „Decyzje projektowe” i pracuj dalej.
