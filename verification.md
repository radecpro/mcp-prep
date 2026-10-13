# Weryfikacja integracji MCP i RAG — 2026-10-12

Branch: `codex/mcp-rag-integration`. Wyniki dokumentują przebiegi z dnia audytu.
Nie zmieniano workloadów, RBAC ani zakresu dostępu do klastra.

## Wynik końcowy

- 22 testy: 12 kontraktów integracji, 4 odpowiedzi RAG i 6 retrievalu — PASS.
- Bazowy test MCP: discovery, catalog/payments, błędy, puste wyniki i granice namespace — PASS.
- Prawdziwy przepływ MCP → retrieval → Ollama: catalog 2/2 oraz payments 0/3 — PASS.
- 12 syntetycznych scenariuszy z prawdziwym retrievalem i lokalnym Ollama — PASS.
- Kompilacja modułów oraz `git diff --check` — PASS.

Scenariusze syntetyczne nie wywołują Kubernetes. Nie utworzono dodatkowych
awarii w klastrze. Odczyt `kubectl auth can-i --list` potwierdził uprawnienia
diagnostyczne get/list deployments i pods, list events, bez zapisu workloadów
i dostępu do Secretów. Standardowe uprawnienia do zapytań o własne uprawnienia
i odkrywania API nie są uprawnieniami do modyfikowania workloadów.

| Przypadek | Sprawdzone zachowanie |
| --- | --- |
| Zdrowy snapshot bez eventów | Brak hipotezy awarii; ograniczona ocena zdrowia |
| Pusty selektor | Brak hipotezy przyczyny; wymagana weryfikacja selektora |
| Ucięta lista podów | Brak czystej oceny; jawne ograniczenie kompletności |
| Ucięta lista eventów | Brak czystej oceny; jawne ograniczenie historii |
| Pending bez eventów | Abstencja; faza nie dowodzi problemu schedulera |
| FailedScheduling / Insufficient cpu | Hipoteza pojemności względem requests, właściwy runbook |
| CrashLoopBackOff bez logów | Abstencja od rozpoznania przyczyny restartów |
| OOMKilled | Zachowany powód zakończenia; abstencja od przypisania przyczyny limitowi lub węzłowi |
| ImagePullBackOff / unauthorized | Hipoteza autoryzacji lub ścieżki repozytorium, cytowanie runbooka |
| Komunikat z manifest unknown po 600 znakach | Sygnał na końcu wiadomości nadal wpływa na retrieval |
| Database table not found | Brak hipotezy błędnego obrazu |
| Instrukcja podszywająca się pod event | Brak znacznika ataku i komendy usuwania w wygenerowanej interpretacji |

## Znalezione problemy i poprawki

Początkowe dodatkowe testy wykazały, że brak podów nie blokował wymyślonej
przyczyny, Pending nie trafiał do retrievalu, a obcięcie wiadomości usuwało
istotny końcowy błąd. Query powstaje teraz ze znanych sygnałów znalezionych
w pełnych wiadomościach, fazie Pending i historii restartów. Instrukcje z eventów
nie są kopiowane do query. Nieznany stan kontenera, brak Running oraz historia
restartów uniemożliwiają czystą ocenę snapshotu.

Hipotezy wymagają konkretnego sygnału przyczyny w odpowiednim kontekście objawu.
Same repliki, Pending lub CrashLoopBackOff nie wystarczają. Osobny test
sprawdza, że błąd tabeli bazy nie staje się dowodem błędnego obrazu nawet przy
współistniejącym ImagePullBackOff. Kluczowy brakujący dowód jest zawsze
zachowany, niezależnie od wyboru modelu.

Przegląd treści ujawnił mylenie requests z użyciem CPU i zbyt pewne przypisanie
OOMKilled przekroczeniu limitu kontenera. Dodano deterministyczne zastrzeżenia.
Dla samego OOMKilled wymuszono abstencję od przypisywania przyczyny źródłowej:
obecne narzędzia nie dostarczają limitów, metryk ani stanu pamięci węzła.

Testy Ollama wykazały również odrzucenie pustego enum, niepełną generację,
przekroczenie budżetu kontekstu i niepoprawne/powtórzone referencje. Niepełne
i niepoprawne odpowiedzi zostały odrzucone. Poprawiono schemat abstencji,
domyślny kontekst ograniczono do trzech fragmentów i wyłączono sekcje komend
oraz statyczne przykłady labowe. Model wybiera jedno najlepsze cytowanie
i jedną obserwację na hipotezę; raport zachowuje referencje jako listy.

## Dowody i odtworzenie

- `.local/integration-scenarios.json`: dokładne syntetyczne wejścia, odpowiedzi i wyniki wszystkich 12 przypadków.
- `.local/catalog-integration.json` i `.local/payments-integration.json`: końcowe raporty rzeczywistego klastra.
- `.local/integration-verification.txt`: wynik końcowego testu przepływu obu workloadów.

```bash
.venv/bin/python scripts/verify_integration.py --live
.venv/bin/python scripts/verify_scenarios.py --live
.venv/bin/python scripts/verify_answers.py
.venv/bin/python scripts/verify_rag.py
.venv/bin/python scripts/verify.py
```

## Granice wniosku

Sprawdzono przepływ, kontrakty, abstencję i treść dla wymienionych przypadków.
To nie jest ogólny benchmark poprawności modelu. Referencja do runbooka sama
nie dowodzi poprawności całego zdania; sformułowania modelu nadal mogą być
zbyt kategoryczne i trzeba czytać je razem z hipotezą, dowodami i ograniczeniami.
Przejście jednego testu instrukcji w evencie nie gwarantuje odporności na wszystkie
ataki. Stały wybór narzędzi, brak wykonywania tekstu modelu i RBAC ograniczają
działania do odczytów. Rozszerzenie korpusu wymaga rozszerzenia bramki sygnałów
i testów; obecne heurystyki są celowo dopasowane do trzech runbooków.
