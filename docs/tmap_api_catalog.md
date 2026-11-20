# 티맵 API 전수 확인 (2026-11-20)

원본 문서 표: `data/tmap_docs/rows/*.txt` (52개, 공식 문서 tmapapi.tmapmobility.com 에서 추출). 요금: openapi.sk.com/products/calc?svcSeq=4&menuSeq=5

## 직접 호출로 확인한 것 (우리 키, 무료 요금제)
| API | 결과 | 쓸모 |
|---|---|---|
| routes (v1, 사용 중) | 회전·도로종류·facilityType(2 터널, 4 지하도로)·교통 [시작,끝,혼잡,속도km/h]. 차선 없음. 안전 지점 turnType 191~194 는 문서엔 있으나 실제 경로 2개에서 안 나옴 | 사용 중 |
| **V2routes** | 200. 회전마다 **방면 이름**(directionName "성남시청/ /분당수서도로"), 교차로 이름, 톨게이트, 링크별 혼잡(No/Little/Heavy/Closed)·속도·시설(Tunnel…)·restrictions, 교통 기준 시각 | 티맵 앱식 "○○ 방면" 표시. 경로 버킷(하루 1,000) 같은 쪽으로 보임(미확인) |
| **road/matchToRoads500** | 경로 좌표 387개 → 838개 지점 제한속도(110·80·60·50·30…)·도로 등급, 1회 호출 | 경로 전체 제한속도 상시 표시. 무료 하루 200회(₩44) |
| **road/nearToRoad** | 도로명·**제한속도**·**차로 수**·일방·tollLink·linkFacil(터널) | 안내 없을 때 제한속도. 지오코딩 버킷 하루 2만 무료 |
| pois/{id} 충전소 | 요금 "295원~350원/kWh", 운영사, 영업시간, totalCnt | 충전소 카드에 요금 |
| pois/search/around 주유소 | 휘발유·경유 가격 들어 있음 | 테슬라엔 불필요 |
| traffic | 링크별 속도·시작/끝 교차로·갱신 시각. trafficType=ACC 는 돌발만(문서) | 돌발 요청 가볍게 가능 |
| routeSequential30 / routeOptimization10 / prediction | 200 | 경유지 순서 최적화(무료 50/일) |
| poi/findPoiRoute (경로 반경 검색) | 우리 호출은 403(경로 확인 필요) | 경로 위 충전소, 빈 충전기 많은 순·kW 필터(문서) |

## 웹에선 못 쓰는 것
- 차선 안내·교차로 확대도·단속카메라·과속방지턱 안내: **TMAP Navi SDK(안드로이드·iOS 전용, 별도 계약)** 에만 있음.
- 실시간 주차 빈자리: 없음. 유가정보 전용 API: 별도 계약.

## JS SDK v3 에 있는데 안 쓰는 것
- `setMapType('HYBRID')` 위성+도로, `Polyline direction:true` 방향 화살표, `Tmapv3.extension.TData.autoTraffic(map)` 지도 전체 실시간 교통 덮개, MarkerCluster, InfoWindow.

## 쓸 만한 순서 (제안)
1. 제한속도 상시 표시 (안내 중 matchToRoads500 경로당 1회, 안내 없을 땐 nearToRoad 몇십 초마다)
2. 회전 카드에 "○○ 방면" (V2routes, 호출 버킷 확인 후)
3. 경로 위 충전소·빈 충전기 순 (findPoiRoute, 403 원인 확인)
4. 충전소 요금 표시, 지도 실시간 교통 덮개(autoTraffic)
5. 출발 정확도: routes 의 gpsInfoList(지나온 궤적)·endRpFlag=8(목적지 쪽 차로)
