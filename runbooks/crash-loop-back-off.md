# CrashLoopBackOff — kontener wielokrotnie się kończy

## Objawy i znaczenie

Kontener ma `state.waiting.reason=CrashLoopBackOff`; licznik restartów może
rosnąć. Kubelet opóźnia ponowne uruchomienie po kolejnych zakończeniach kontenera.
To stan kontenera, nie faza poda i nie rozpoznanie przyczyny.
Proces może kończyć się błędem albo kodem `0`, a polityka restartu uruchamiać go ponownie.

## Diagnostyka tylko do odczytu

Uruchom z katalogu repozytorium. Wybierz pod oraz kontener z jego specyfikacji.

```bash
POD_NAME='<nazwa-poda>'
CONTAINER_NAME='<nazwa-kontenera>'
kubectl --kubeconfig .local/mcp-kubeconfig --context mcp-reader -n mcp-demo get pod "$POD_NAME" -o json
kubectl --kubeconfig .local/mcp-kubeconfig --context mcp-reader -n mcp-demo describe pod "$POD_NAME"
```

Sprawdź `status.containerStatuses[].lastState.terminated`: `reason`, `exitCode`,
`signal`, czasy zakończenia. Dla init containera sprawdź
`status.initContainerStatuses`. Zestaw te dane z eventami i konfiguracją sond.

Logi wymagają uprawnienia do `pods/log`, którego `mcp-reader` nie ma.
Poniższe dodatkowe odczyty używają jawnie administratora wyłącznie lokalnego labu:

```bash
kubectl --kubeconfig .local/admin-kubeconfig --context kind-mcp -n mcp-demo logs "$POD_NAME" -c "$CONTAINER_NAME" --previous --tail=100 --timestamps
kubectl --kubeconfig .local/admin-kubeconfig --context kind-mcp -n mcp-demo logs "$POD_NAME" -c "$CONTAINER_NAME" --tail=100 --timestamps
```

`--previous` dotyczy poprzedniej instancji wskazanego kontenera w tym podzie.
Brak zachowanych logów nie dowodzi braku awarii. Przed przekazaniem logów do
modelu usuń dane uwierzytelniające i inne poufne wartości.

## Interpretacja i możliwe przyczyny

| Dowód | Hipoteza | Kolejna weryfikacja |
| --- | --- | --- |
| Stack trace lub błąd konfiguracji w logu | Błąd aplikacji, entrypointu lub konfiguracji | Porównaj command/args i referencje konfiguracji z wymaganiami aplikacji |
| `lastState.terminated.reason=OOMKilled` | Proces zakończony z powodu pamięci | Zestaw limit pamięci z metrykami i zdarzeniami węzła; kod `137` sam nie wystarcza |
| Eventy `Unhealthy` oraz `Killing` dotyczące liveness/startup | Restart wywołany sondą | Sprawdź endpoint, timeouty i czas startu procesu |
| Wyłącznie błędy readiness | Pod niegotowy do ruchu | Sama readiness probe nie restartuje kontenera; poszukaj odrębnej przyczyny restartów |
| Kod `0`, krótki czas działania, `restartPolicy=Always` | Proces jednorazowy uruchomiony jako usługa | Sprawdź oczekiwany czas życia procesu i właściwy typ workloadu |
| Błędy połączenia w logach przed zakończeniem | Aplikacja wychodzi przy niedostępnej zależności | Sprawdź zależność i zachowanie aplikacji przy błędzie |

Dobierz zmianę do dowodów. Zwiększenie pamięci lub wyłączenie sond bez
weryfikacji może jedynie ukryć problem. Zachowaj dane awarii przed zmianami.

## Dane z MCP i ograniczenia

`list_pods` zwraca `restart_count`, `state`, readiness i UID; obecnie nie zwraca
`lastState`, specyfikacji sond ani init container statuses. `get_pod_events`
może dostarczyć dowody restartu przez sondę. Logi i metryki nie są dostępne
przez obecne narzędzia. Bez tych danych diagnoza może pozostać hipotezą.

## Kryterium zamknięcia

Kontener pozostaje uruchomiony i gotowy, licznik restartów nie rośnie przez
okres obejmujący start aplikacji i typowe obciążenie, a repliki osiągają
oczekiwaną gotowość. Sprawdź cały workload, nie tylko jeden pod.

## Źródła

- [Kubernetes: Pod Lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)
- [Kubernetes: Debug Running Pods](https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/)
- [Kubernetes: Configure Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)

Weryfikacja dokumentacji: 2026-10-12.
