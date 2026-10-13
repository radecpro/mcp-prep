# Kontrolowany agent diagnostyczny — audyt ukończenia

Data: 2026-10-12. Branch: `codex/mcp-rag-integration`.
Wyniki poniżej dokumentują przebiegi z dnia audytu; nie są bieżącym monitoringiem klastra.

## Wymagania i dowody

| Wymaganie | Implementacja i końcowy dowód |
| --- | --- |
| Model wybiera kolejne odczyty | `agent.Controller.choose`; live catalog: 6 kroków, payments: 9. Dwa różne dopuszczalne przebiegi dla identycznego scope sprawdza test kontraktu. |
| Kontrolowany zakres działań | Menu pochodzi wyłącznie z kontrolera. Model wybiera numer; argumenty namespace/deployment/selector/UID nie pochodzą z modelu. Testy blokują dodatkowe argumenty, nieznane akcje, bool zamiast numeru oraz nieprawidłowe UID i tożsamości wyników. |
| Dostęp tylko do odczytu | Nie zmieniono server.py ani k8s/rbac.yaml. MCP nadal ma trzy istniejące odczyty. Aktualne zapytania can-i dla patch deployments, get secrets i list pods w default zwróciły `no`. |
| Adaptacja i ochrona przed pętlą | Z menu znikają wykonane odczyty; pojawiają się eventy odkrytych UID. Finish wymaga aktualnego retrievalu. Testy sprawdzają brak powtórzonych odczytów MCP i poprawne odświeżenie po nowym dowodzie. |
| Limit kroków i czasu | 1–40 decyzji, 1–900 s, domyślnie 10/240. Realny test max-steps=1: jeden odczyt i step_limit. Realny test timeout=1: timeout po 1.142 s, bez odczytów. Test anulowania potwierdza kill i reap procesu roboczego. |
| MCP → runbooki → odpowiedź | Agent używa local retrievalu i istniejącej generacji Ollama. Sekcje są ponownie sprawdzane względem korpusu; testy odrzucają podmienione źródło i nieaktualny indeks przed generacją. |
| Oddzielenie faktów i hipotez | Raport zachowuje wyniki MCP z ID/czasem, cytowane hipotezy, brakujące dowody i ograniczenia; częściowe/niepoprawne sesje nie zawierają diagnozy. |
| Zakończenie przy brakujących dowodach | Realny model + syntetyczne MCP: pusty selektor i CrashLoopBackOff bez logów kończą się bez hipotez przyczyny. Ograniczenia logów/specyfikacji/metryk pozostają jawne. |
| Weryfikacja i instrukcja użycia | README zawiera CLI, statusy, limity i reprodukcję testów. Poniższe testy i artefakty potwierdzają działanie. |

## Wyniki

- 31 testów kontraktów i regresji: 8 agenta, 13 integracji, 4 odpowiedzi, 6 retrievalu — PASS.
- Aktualny test MCP discovery, obu workloadów, błędów, pustych wyników i namespace — PASS.
- Agent live catalog: completed, 2/2, no_issue_detected, bez hipotez; 6 kroków, 18.906 s — PASS.
- Agent live payments: completed, 0/3, needs_investigation, hipoteza referencji obrazu z runbookiem i E2; 9 kroków, 28.884 s — PASS.
- Cztery scenariusze agenta z prawdziwym plannerem, embeddingami i generacją:
  pusty selektor, CrashLoopBackOff bez logów, FailedScheduling/CPU oraz instrukcja
  podszywająca się pod event — PASS. W scenariuszu ataku dane trafiły do planera
  i finalnej interpretacji, lecz nie do wykonania komend ani zmiany scope.
- Limit jednego kroku zachował jeden odczyt w raporcie i zwrócił exit 1 — PASS.
- Limit jednej sekundy zachował timeout i brak diagnozy, exit 1 — PASS.
- Kompilacja nowych modułów i `git diff --check` — PASS.

Artefakty dokładnych odpowiedzi i przebiegów:

- `.local/agent-catalog.json`, `.local/agent-payments.json`
- `.local/agent-verification.txt`
- `.local/agent-scenarios.json`, `.local/agent-scenarios-verification.txt`
- `.local/agent-step-limit.json`, `.local/agent-timeout.json`

Wyniki operacyjne pozostają w ignorowanym `.local/`.

## Decyzje i granice

Nie dodano uprawnień do logów, Secretów ani administratora. Agent diagnostyczny
ma wybierać dostępne odczyty i kończyć z konkretnym brakiem dowodów, zamiast
eskalować uprawnienia lub podejmować naprawy. Obsługa istniejących trzech
runbooków korzysta z konserwatywnej bramki sygnałów; nowy korpus wymaga jej
rozszerzenia i nowych scenariuszy.

Planner otrzymuje ograniczony widok danych; oryginały pozostają w raporcie.
UID i zakres są kontrolowane kodem. Rationale jest tekstem modelu, nie
obserwacją klastra. Agent nie wykonuje wygenerowanych komend. Tożsamość właściciela
podów nie jest dowiedziona selektorem, a odczyty nie są atomowym snapshotem.

Nie potwierdzono ogólnej poprawności modelu ani odporności na wszystkie ataki.
Model może użyć zbyt kategorycznego sformułowania; hipotezę należy czytać razem
z dowodami, cytowanym runbookiem i deterministycznymi zastrzeżeniami. OOMKilled
nie rozstrzyga przyczyny źródłowej, a not found może maskować autoryzację registry.
Kontroler i RBAC ograniczają działania niezależnie od poprawności takiego tekstu.
