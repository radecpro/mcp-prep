# Pending — pod nie osiąga etapu uruchomienia

## Objawy i znaczenie

`status.phase=Pending` oznacza, że pod został przyjęty, lecz przygotowanie
kontenerów nie zostało zakończone. Nie oznacza automatycznie problemu schedulera:
pod może już mieć węzeł i czekać na obraz, wolumen lub init container.
Kolumna `STATUS` w `kubectl get pods` nie zawsze odpowiada fazie poda.

## Diagnostyka tylko do odczytu

Uruchom z katalogu repozytorium i wybierz konkretny pod.

```bash
POD_NAME='<nazwa-poda>'
kubectl --kubeconfig .local/mcp-kubeconfig --context mcp-reader -n mcp-demo get pod "$POD_NAME" -o json
kubectl --kubeconfig .local/mcp-kubeconfig --context mcp-reader -n mcp-demo describe pod "$POD_NAME"
```

Najpierw sprawdź `.spec.nodeName` oraz condition `PodScheduled`:

- Bez węzła: sprawdź `FailedScheduling`, requests, selektory, affinity,
  tolerations, topology spread i ewentualne scheduling gates.
- Z przypisanym węzłem: sprawdź stany kontenerów/init containerów oraz eventy
  dotyczące pobierania obrazu, montowania wolumenów i tworzenia sandboxa.

## Interpretacja i możliwe przyczyny

| Dowód | Hipoteza | Kolejna weryfikacja |
| --- | --- | --- |
| `FailedScheduling`: `Insufficient cpu` / `Insufficient memory` | Requests nie mieszczą się na kwalifikujących się węzłach | Porównaj requests z allocatable i już przydzielonymi requests; niskie użycie CPU nie dowodzi wolnej pojemności dla schedulera |
| Niedopasowanie node selector lub node affinity | Brak węzła spełniającego warunki | Porównaj etykiety węzłów z wymaganiami poda |
| `untolerated taint` | Taint wyklucza węzeł | Sprawdź taint i sens toleration; toleration nie gwarantuje przydziału |
| `unbound immediate PersistentVolumeClaims` | PVC blokuje scheduling | Sprawdź binding PVC, StorageClass i eventy provisionera |
| Przypisany węzeł, `FailedMount` / `FailedAttachVolume` | Problem przygotowania storage | Sprawdź eventy PVC i sterownika CSI oraz dostępność wskazanych zasobów |
| Przypisany węzeł, `ErrImagePull` / `ImagePullBackOff` | Problem pobierania obrazu | Przejdź do runbooka `image-pull-backoff.md` |
| `FailedCreatePodSandBox` | Problem runtime lub konfiguracji sieci poda | Przekaż komunikat operatorowi węzła/CNI; sam event nie identyfikuje konkretnej awarii |

Dodatkowe odczyty poniżej wymagają szerszych uprawnień niż `mcp-reader`.
Używają jawnie administratora wyłącznie lokalnego labu:

```bash
kubectl --kubeconfig .local/admin-kubeconfig --context kind-mcp get nodes -o wide
NODE_NAME='<nazwa-węzła>'
kubectl --kubeconfig .local/admin-kubeconfig --context kind-mcp describe node "$NODE_NAME"
kubectl --kubeconfig .local/admin-kubeconfig --context kind-mcp -n mcp-demo get pvc
PVC_NAME='<nazwa-pvc>'
kubectl --kubeconfig .local/admin-kubeconfig --context kind-mcp -n mcp-demo describe pvc "$PVC_NAME"
```

Nie zmniejszaj requests ani nie dodawaj tolerations bez sprawdzenia potrzeb
workloadu. Najpierw ustal blokujący warunek; zmiana może przenieść awarię na węzeł.
PVC `Pending` z `WaitForFirstConsumer` może oczekiwać na wybór węzła zgodnie
z konfiguracją storage i samo nie dowodzi awarii provisionera.

## Dane z MCP i ograniczenia

`list_pods` dostarcza fazę, stan kontenera i UID; `get_pod_events` może pokazać
`FailedScheduling`. Obecne narzędzia nie zwracają `nodeName`, conditions,
requests ani specyfikacji PVC i węzłów. Rozstrzygnięcie gałęzi diagnostycznej
może wymagać dodatkowego odczytu. Brak eventów nie potwierdza braku problemu.

## Kryterium zamknięcia

Pod ma węzeł, zakończył wymagane przygotowanie i init containery, a kontenery
aplikacji są gotowe. Sama zmiana fazy na `Running` nie wystarcza; dla Deploymentu
sprawdź gotowość oczekiwanych replik.

## Źródła

- [Kubernetes: Pod Lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)
- [Kubernetes: Debug Pods](https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/)
- [Kubernetes: Assigning Pods to Nodes](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/)
- [Kubernetes: Storage Classes](https://kubernetes.io/docs/concepts/storage/storage-classes/#volume-binding-mode)

Weryfikacja dokumentacji: 2026-10-12.
