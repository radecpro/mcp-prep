# ImagePullBackOff — nie można pobrać obrazu

## Objawy i znaczenie

Kontener ma `state.waiting.reason=ErrImagePull` lub `ImagePullBackOff`.
`ImagePullBackOff` oznacza opóźnienie kolejnej próby pobrania po błędzie;
nie identyfikuje przyczyny. Pod może mieć fazę `Pending` mimo przypisania do węzła.
Event `BackOff` opisuje ponawianie, a event `Failed` może zawierać właściwy błąd.

## Diagnostyka tylko do odczytu

Uruchom z katalogu repozytorium. Wybierz nazwę poda z listy; selektor
`app=payments` jest konwencją tego labu.

```bash
kubectl --kubeconfig .local/mcp-kubeconfig --context mcp-reader -n mcp-demo get pods -l app=payments
POD_NAME='<nazwa-poda>'
kubectl --kubeconfig .local/mcp-kubeconfig --context mcp-reader -n mcp-demo get pod "$POD_NAME" -o jsonpath='{range .spec.containers[*]}{.name}{"\t"}{.image}{"\n"}{end}'
kubectl --kubeconfig .local/mcp-kubeconfig --context mcp-reader -n mcp-demo describe pod "$POD_NAME"
```

Sprawdź również `.spec.initContainers`, jeśli błąd dotyczy init containera.
Porównaj dokładną nazwę obrazu, tag lub digest z komunikatem dla tego kontenera.
Eventy mogą wygasnąć; ich brak nie wyklucza awarii.

## Interpretacja i możliwe przyczyny

| Komunikat w evencie | Hipoteza | Kolejna weryfikacja |
| --- | --- | --- |
| `manifest unknown`, `not found` | Nieistniejący tag, digest lub repozytorium | Sprawdź referencję w registry; prywatne registry mogą maskować brak dostępu jako brak zasobu |
| `unauthorized`, `denied`, `pull access denied` | Brak uprawnień lub niewłaściwa ścieżka repozytorium | Sprawdź referencje `imagePullSecrets`, ServiceAccount oraz uprawnienia konta w registry |
| `FailedToRetrieveImagePullSecret` | Niedostępny Secret wskazany przez pod | Uprawniony operator sprawdza nazwę i namespace Secretu |
| `timeout`, `no such host`, błąd `x509` | Sieć, DNS lub zaufanie TLS po stronie węzła/runtime | Sprawdź dostęp węzła do registry; test z laptopa nie potwierdza tej ścieżki |
| `429`, `Too Many Requests` | Limit registry | Sprawdź limity i sposób uwierzytelnienia pobrań |

Nie umieszczaj wartości Secretów ani tokenów w odpowiedzi diagnostycznej.
Naprawa powinna dotyczyć potwierdzonej przyczyny: referencji obrazu,
autoryzacji lub dostępu do registry. Sam restart nie usuwa przyczyny.

## Dane z MCP i ograniczenia

`get_deployment_status` pokazuje wpływ na repliki. `list_pods` dostarcza UID,
stan kontenera i komunikat oczekiwania. `get_pod_events` pobiera eventy po UID.
Obecne narzędzia nie zwracają specyfikacji obrazu ani `imagePullSecrets`;
wymagają one dodatkowego odczytu poda. MCP nie ma dostępu do Secretów.
Listy mogą być ucięte, a klient pobiera eventy tylko pierwszego poda.

## Przykład z labu i kryterium zamknięcia

Manifest `k8s/demo.yaml` ustawia dla `payments` obraz
`nginx:mcp-demo-nonexistent`. Jest to celowo błędna referencja w labie.
To nie jest bieżąca obserwacja klastra: potwierdź obraz i event przed diagnozą.
Po naprawie sprawdź uruchomienie kontenerów oraz gotowość wszystkich oczekiwanych
replik. Usunięcie `ImagePullBackOff` samo nie potwierdza zdrowia aplikacji.

## Źródła

- [Kubernetes: Images](https://kubernetes.io/docs/concepts/containers/images/)
- [Kubernetes: Debug Pods](https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/)

Weryfikacja dokumentacji: 2026-10-12.
