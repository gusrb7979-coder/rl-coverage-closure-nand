# 강화학습 기반 Coverage Closure: NAND 컨트롤러 오류 복구 로직의 Deep Corner Case 버그 검출 (ver 1.0)

무작위 NAND 오류 응답에 반응하는 강화학습 기반 UVM 검증 방법론

NAND 읽기 오류 복구 컨트롤러(가상 IP)의 가장 깊은 **중첩 오류 경로**에 심은 버그를, 강화학습(표 형태
Q-learning) 에이전트가 커버리지 보상만으로 찾아내는 PoC입니다. CRV, 커버리지 퍼저, BFS와 같은 조건에서
비교했고, 같은 결과를 파이썬 모델과 실제 RTL 시뮬레이션(Icarus + cocotb + pyuvm) 양쪽에서 확인했습니다.

## 현업에서 어디에 쓰는가

이 PoC는 **NAND 컨트롤러와 NAND 소자를 함께 검증하는 서브시스템·시스템 단계의 UVM 검증(DV)**을
겨냥합니다. 가정한 시나리오는 다음과 같습니다.

1. **IP 설계 단계: 깊은 경로에 휴먼 에러가 남는다.** 블록 단위 검증은 정상 복구 경로를 중심으로 이루어지고,
   오류가 세 번 겹치는 경로는 드물다고 보고 덜 다루기 쉽습니다. 이 PoC의 버그(재기록 슬롯 계산의 off-by-one)는
   그런 깊은 경로에 숨은 채 통합 단계로 넘어온 설계 결함입니다.
2. **서브시스템 DV 단계: 오류 응답을 테스트벤치가 정할 수 없다.** NAND 소자 모델이 자체 오류 모델로 실패를
   만들거나 에뮬레이션·실제 NAND가 붙으면, 실패 시점과 실패 정보는 소자 쪽에서 무작위로 나옵니다. 테스트벤치(호스트
   역할)는 실패 정보를 0, 1, 2… 순서로 강제할 수 없고, 매번 돌아온 응답을 보고 맞는 명령을 골라야 가장 깊은 복구 경로에
   닿습니다.
3. **Pain point: coverage closure가 막힌다.** 무작위 자극이 IDLE에서 버그(깊이 8)에 한 번에 닿을 확률은 약
   4.4×10⁻¹⁶(2,250조 분의 1)입니다. 트랜잭션 64종(opcode 4종 × param 16종) 중 상태마다 정답 1종을 8번
   고르고, 확률 0.5인 NAND 실패가 3번 일어나야 하므로 (1/64)⁸ × (1/2)³ = 2⁻⁵¹입니다. 저장한 입력을 다시 넣어도 NAND 결과가 달라 같은 경로가 재현되지 않습니다.
   그래서 DV 엔지니어가 스펙을 분석해 실패 정보마다 반응하는 시퀀스를 손으로 작성하고, NAND 세대가 바뀌어 retry 표가
   달라지면 다시 작성합니다.
4. **이 PoC: 반응형 시퀀스 작성을 RL로 자동화한다.** 에이전트는 커버리지 보상만 받고, DUT 출력(상태, 실패 정보)을 보고
   다음 트랜잭션을 고르는 규칙을 RTL 시뮬레이션 루프 안에서 학습합니다.

| 현업 pain point | 이 PoC의 대응 | UVM 결과 |
|---|---|---|
| 무작위 응답 때문에 CRV나 저장된 입력으로는 깊은 경로에 닿지 못함 | 응답을 보고 다음 명령을 고르는 정책을 학습 | 버그 검출: RL 10/10, CRV·퍼저·BFS 0/30 |
| 반응형 시퀀스를 사람이 손으로 작성 | 커버리지 보상만으로 자동 생성 | 스펙 커버리지 71/71 (시드 10개 모두) |
| NAND 세대마다 retry 표가 바뀌어 테스트를 다시 작성 | 테스트 수정 없이 재학습 | Read Retry·예비 블록 표만 바꾼 버그 RTL 3종 모두 검출 |
| 찾은 코너 케이스를 회귀 테스트로 다시 쓰기 어려움 | 정책표(관측 144개 → 트랜잭션)를 새 오류 시드에서 재생 | 버그 도달 98.4~100%, 정상 DUT 오탐 0 |

### PoC에서 이 조건을 재현한 방법

- **검증 대상은 NAND 컨트롤러, 오류원은 연결된 NAND 소자.** NAND 소자의 무작위 오류(전하 누설, 온도, 마모에 따른
  읽기·쓰기 실패)는 16비트 LFSR 소자 모델로 정의했고, 트랜잭션마다 실패 여부(p = 0.5)와 실패 정보를 뽑습니다.
  시뮬레이션 편의상 이 소자 모델을 컨트롤러 RTL과 한 모듈로 묶었습니다. 자극 생성기는 실제 호스트처럼 상태(`state_o`)와 실패 정보(`hint_o`: NAND 실패 시 4비트로 알려 주는 부가 정보. 읽기 실패면 비트 오류 수, 쓰기 실패면 어디서 실패했는지를 나타냄)를 **관찰만 할 수 있고 통제할 수
  없습니다.**
- **그레이박스 조건.** 모든 방법(CRV·퍼저·BFS·RL)은 DUT의 출력 포트(`state_o`, `hint_o`)와 모니터·스코어보드
  이벤트를 관찰합니다. RTL 코드, retry 표·예비 블록 표의 내용, 버그 위치는 어느 방법도 모릅니다.

## 폴더 구성

```
spec/           DUT 사양 (상태, 상수, retry/예비 블록 표, NAND 소자 오류 모델(LFSR), 커버리지 정의) — 모델과 RTL의 단일 소스
rtl/            nand_recovery_golden.v (정상 설계), nand_recovery_buggy.v (버그 버전, 정상과 한 줄 차이)
nandpoc/        공용 파이썬: nand_dut (모델), rl_agent (Q-learning), methods (CRV·퍼저·BFS·RL)
flow1_python/   흐름 1: 파이썬 모델에서 비교 실험, 유효성 점검, 정책 추출, 그래프
synth/          Yosys 합성 가능성 검사 + 합성 넷리스트와 모델의 게이트 수준 일치 검증 (Windows/WSL 공용)
flow2_uvm/      흐름 2: WSL + Icarus + cocotb + pyuvm 테스트벤치와 실행·비교 스크립트
supplementary/  보조 실험: 응답이 고정된 FSM 대조(deterministic_lock), 응답에 담긴 난수를 다음 입력이 따라야 하는 경우(nonce)
results/        2026-09-27 최종 실행 결과 (증거 보관, 현재 RTL 기준)
out/            새로 실행한 결과가 저장되는 곳 (.gitignore 대상)
```

## FSM 상태

| 상태 | 의미 | 상태 | 의미 |
|---|---|---|---|
| IDLE | 명령 대기 | RELOCATED | 다른 예비 블록에 재배치 완료 |
| ECC_FAIL | 읽기 실패 (ECC 교정 불가) | ECC_FAIL2 | 재배치한 데이터 재읽기 실패 |
| RECOVERED | Read Retry로 읽기 복구 | RECOVERED2 | 재읽기 실패를 Read Retry로 복구 |
| PGM_FAIL | 재배치 쓰기(PGM) 실패 | MAP_PENDING | 매핑 확정 대기 |

전체 전이는 `docs/fsm_golden.png`(정상)와 `docs/fsm_buggy.png`(버그)에 있습니다.

## 심은 버그

정상 설계는 재배치 쓰기가 실패하면 첫 번째 매핑 예약을 취소하고, 재배치한 데이터 재읽기 실패를 복구한 뒤에는 재기록용 예약을
**가장 최근 슬롯**에 덮어씁니다. 버그 버전은 가장 최근 슬롯 번호를 계산할 때 -1을 빠뜨려(off-by-one) 취소된
슬롯을 되살리고, 마지막 확정에서 매핑을 2건 기록합니다(데이터 유실). 두 RTL의 코드 차이는 한 줄이고, 합성과
정적 검사로는 걸리지 않는 기능 버그입니다(사용하지 않는 신호도 남지 않음).

```diff
-    wire [1:0]  rsv_last   = rsv_idx - 2'd1;      // index of the most recent reservation
+    wire [1:0]  rsv_last   = rsv_idx;             // index of the most recent reservation
     wire        rearm_slot = rsv_last[0];     // overwrite the most recent reservation
```

버그에 도달하려면 무작위 실패 3번(읽기, 재배치 쓰기, 재배치한 데이터 재읽기)이 모두 일어나고, 매번 DUT가 보고한 실패 정보에 맞는
파라미터로 대응해야 합니다(깊이 8).

## 커버리지와 보상

**커버리지 빈 73개 = 스펙 커버리지 71개 + 스펙 위반 이벤트 2개.** 스펙 커버리지는 RTL 상태 8개, 상태 전이 15개,
복구 단계별 실패 정보 48개(3단계 × 16)입니다. 위반 이벤트(가상 상태 8과 전이 7→8)는 "확정 1회에 매핑 1건" 규칙이
깨진 순간이며, 실제로는 스코어보드 검사기의 이벤트입니다. 그래서 결과는 "스펙 커버리지 71/71 + 위반 검출"로
나누어 보고합니다. 정상 설계에서는 위반 빈에 도달할 수 없으므로 71/71이 최대입니다.

**보상 = 새로 채운 빈 수 + 호기심 1/√N(관측) + 위반 검출 시 10.** 보상의 재료는 모두 사양서(커버리지 정의,
확정 규칙)와 모니터·스코어보드 출력입니다. RTL 코드, retry 표·예비 블록 표, 버그 위치는 쓰지 않습니다.
관측은 출력 포트 값(상태, 실패 정보)이고, 행동은 트랜잭션 64종 중 하나입니다.

**학습 = 표 형태 Q-learning.** 식과 기호는 Sutton & Barto 교재·위키피디아의 표준 표기를 따릅니다. 대문자 S_t, A_t는
t번째 트랜잭션에서 관측한 상태와 보낸 행동이고, 그 결과로 정해지는 다음 상태와 보상에는 t+1을 붙입니다. 소문자 a는
특정 행동이 아니라 64종 행동을 모두 대입해 보는 변수입니다.

$$R_{t+1} = \Delta C_{t+1} + \frac{\beta}{\sqrt{N(S_{t+1})}} + 10 \cdot \mathbb{1}[\text{violation}_{t+1}]$$

$$Q^{new}(S_t, A_t) \leftarrow (1 - \alpha) \cdot Q(S_t, A_t) + \alpha \cdot \left( R_{t+1} + \gamma \cdot \max_{a} Q(S_{t+1}, a) \right)$$

$$A_t = \begin{cases} \arg\max_{a} Q(S_t, a) & \text{확률 } 1 - \varepsilon \\ \text{무작위 행동} & \text{확률 } \varepsilon \end{cases}$$

학습률 α 0.5, 할인율 γ 0.9, 탐험률 ε 0.1, 호기심 β 1, 모든 Q의 초기값 10(낙관적: 안 해 본 행동이 더 커 보여 먼저
시도)이고, 위반을 처음 검출하면 탐색에서 재현으로 전환해 α 0.2, γ 0.99, β 0으로 바꿉니다. 위반을 검출한 스텝은 종료
상태로 보아 목표값을 R_{t+1}만으로 둡니다.

## 실행 방법

### 흐름 1: 파이썬 모델 + 합성 검사 (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-windows.txt
.\.venv\Scripts\python synth\synth_check.py              # Yosys 합성 + 게이트 수준 일치 (두 버전)
.\.venv\Scripts\python flow1_python\compare.py seeds=10   # CRV/퍼저/BFS/RL 비교 -> out\nand_compare.json
.\.venv\Scripts\python flow1_python\validate.py           # 도달 가능성, 10배 예산, 표 교체, 정상 버전 오탐
.\.venv\Scripts\python flow1_python\export_policy.py 0    # 정책표 -> out\policy_seed0.json
.\.venv\Scripts\python flow1_python\plot.py               # out\fig_coverage_closure.png
.\.venv\Scripts\python supplementary\nonce\nonce_exp.py n_actions=64 seeds=5   # results\supplementary\nonce_results.json
```

### 흐름 2: 실제 RTL 시뮬레이션 UVM (WSL Ubuntu 24.04)

```powershell
$p = "/mnt/c/Users/admin/projects/rl_coverage_poc_nand_ver1.0"
wsl -d Ubuntu-24.04 -u root -- bash $p/flow2_uvm/setup_wsl.sh          # 최초 1회: Icarus, Yosys, cocotb, pyuvm
wsl -d Ubuntu-24.04 -u root -- bash $p/flow2_uvm/uvm_matrix.sh         # 대조 실험 80개 (병렬, 약 1시간 20분)
wsl -d Ubuntu-24.04 -u root -- bash $p/flow2_uvm/uvm_suite.sh synth    # WSL에서 합성 검사
.\.venv\Scripts\python flow2_uvm\make_table_variants.py                 # 표 교체 RTL 변형 3개 (rtl/variants/)
wsl -d Ubuntu-24.04 -u root -- bash $p/flow2_uvm/uvm_jobs.sh extra jobs_extra_stage1.txt jobs_extra_stage2.txt   # 추가 점검 44개
wsl -d Ubuntu-24.04 -u root -- bash $p/flow2_uvm/wsl_uvm.sh variant=buggy mode=fuzzer seed=7 budget=30000000 suffix=_b30m   # 예산 10배
.\.venv\Scripts\python flow2_uvm\matrix_summary.py   # 대조표, 버그 DUT 커버리지 곡선·최대 탐색 깊이
.\.venv\Scripts\python flow2_uvm\matrix_plot.py      # out\fig_uvm_coverage_buggy.png
.\.venv\Scripts\python flow2_uvm\extra_summary.py    # 정책 재사용, 오라클, 표 교체, 예산 10배, 실패 정보 분포
.\.venv\Scripts\python flow2_uvm\cross_check.py      # UVM 결과 전부를 같은 조건의 파이썬 결과와 비교
```

대조 실험 = 정상·버그 DUT × CRV·퍼저·BFS·RL × 시드 0~9, 실행마다 300만 트랜잭션(RL은 빈 73개를 모두 채우면 종료).
추가 점검 = RL 정책 다듬기(RTL 루프 안) 후 정책 재생(버그·정상 DUT), 오라클 도달, 정상 DUT 오라클, 표 교체 RTL 3개.
진행 상황은 `out/matrix_status.txt`·`out/extra_status.txt`, 실행별 로그는 `out/matrix_logs/`·`out/extra_logs/`에 남습니다.
결과는 모두 UVM(흐름 2) 기준이고, 흐름 1(파이썬)은 같은 조건에서 결과가 일치하는지 교차 확인하는 데 씁니다.
개별 실행: `wsl ... bash $p/flow2_uvm/wsl_uvm.sh variant=buggy mode=rl seed=0 budget=3000000`.

**UVM 테스트벤치 구성:** 드라이버(valid/ready 핸드셰이크), 모니터, 커버리지 수집기(스펙 빈 71개 + 위반 빈 2개,
커버리지 곡선, 최대 탐색 깊이), 스코어보드(정상 설계 참조 모델 + "확정 1회에 매핑 1건" 규칙).
스펙 위반이 있으면 테스트가 FAIL합니다.

## 결과 요약 (2026-09-27, `results/`)

`results/`는 현재 RTL(버그 줄 `rsv_last = rsv_idx`)로 실행한 결과입니다. `results/flow1_python/`은 흐름 1과
합성 검사, `results/flow2_uvm/`은 UVM 대조 실험 80개와 추가 점검 45개의 결과, 요약, 그래프, 교차 검증입니다.

**UVM 대조 실험 (시드 10개, 실행마다 300만 트랜잭션)**

| DUT | 방법 | 판정 | 스펙 커버리지 (중앙값) | 빈 73개 커버리지 (중앙값) | 버그 검출 | 최대 탐색 깊이 (시드 0~9) |
|---|---|---|---|---|---|---|
| 정상 | CRV | PASS 10 | 27/71 | 37.0% | 0/10 | — |
| 정상 | 퍼저 | PASS 10 | 31.5/71 | 43.2% | 0/10 | — |
| 정상 | BFS | PASS 10 | 30.5/71 | 41.8% | 0/10 | — |
| 정상 | RL | PASS 10 | 71/71 | 97.3% | 0/10 | — |
| 버그 | CRV | PASS 10 (놓침) | 27/71 | 37.0% | 0/10 | 3,3,3,2,3,3,3,3,3,3 |
| 버그 | 퍼저 | PASS 10 (놓침) | 31.5/71 | 43.2% | 0/10 | 3,5,3,4,4,3,4,7,3,4 |
| 버그 | BFS | PASS 10 (놓침) | 30.5/71 | 41.8% | 0/10 | 4,4,4,3,3,3,4,3,4,4 |
| **버그** | **RL** | **FAIL 10 (검출)** | **71/71** | **100%** | **10/10** | **8 (전부)** |

정상 DUT는 40개 모두 PASS, 버그 DUT에서는 RL만 커버리지 100%에 도달해 버그를 검출했습니다(검출 중앙값
870,637번째 트랜잭션). 깊이 8이 버그이고, 정상 DUT의 빈 73개 기준 최대는 97.3%(위반 빈 2개는 도달 불가)입니다.
그래프: `results/flow2_uvm/fig_uvm_coverage_buggy.png`.

| 항목 | 결과 |
|---|---|
| 합성 (Yosys 0.69 / WSL Yosys 0.33) | 두 버전 모두 경고 없음. 정상·버그 셀 304·299개 / 400·399개, 플립플롭 38개 |
| 게이트 수준 일치 (10만 트랜잭션) | 두 버전 모두 불일치 0건. 매핑 이중 기록: 정상 0번, 버그 459번 |
| 예산 10배 (UVM, 퍼저 시드 7, 3천만) | 버그 미검출(PASS), 스펙 커버리지 54/71. 깊이 7 도달 4번(300만까지는 1번), 깊이 8은 0번 |
| 정책 재사용 (UVM) | RTL 루프 안 정책 다듬기 중앙값 300,110 트랜잭션. 새 오류 시드 1,000회 재생: 버그 DUT 98.4~100% 도달, 정상 DUT 0회 |
| 도달 가능성 (UVM) | 두 표를 아는 오라클이 2,805~5,594 트랜잭션 만에 빈 73개 전부 (시드 5개) |
| 정상 버전 오탐 (UVM) | RL 10개 스펙 71/71·위반 0회, 오라클 20만 트랜잭션(가장 깊은 확정 약 8,750회)에서도 이중 기록 0회 |
| 표 교체 (UVM) | RL 시퀀스를 VIP처럼 재사용: NAND 세대 교체를 가정해 Read Retry·예비 블록 표만 무작위로 바꾼 버그 RTL 3종에서 RL이 재학습만으로 100% 도달·검출(821,299~1,193,152번째), 정책 재현율 98.5~99.4% |
| 실패 정보 분포 (UVM) | ECC_FAIL2 진입 시 실패 정보 16가지, 43,071번 중 최소/최대 비율 0.925 |
| UVM 정합성 | UVM 실행 125개(대조 80, 추가 45) 모두 같은 조건의 파이썬 결과와 일치 |

## 한계

- retry 표와 실패 정보 대응(실패 정보 하나에 정답 하나, 틀리면 중단), 오류 확률 0.5는 단순화입니다.
- 퍼저는 입력 뒤에 이어 붙이는 방식이며, 중간 삽입·삭제를 하는 더 강한 퍼저와는 비교하지 않았습니다.
- 표 형태 Q-learning은 관측이 수천 개를 넘는 큰 설계로는 확장되지 않습니다.
- 사양, 버그, 커버리지 정의를 모두 직접 설계했습니다(가상 IP).
- 상태 출력(`state_o`)을 관찰할 수 있다는 그레이박스 가정이 전제이고, 어떤 신호를 관측으로 볼지(이번엔 `state_o`,
  `hint_o`)와 강화학습 파라미터(α·γ·ε·β) 튜닝을 IP마다 사람이 정해야 합니다.
- 설계가 바뀌면 테스트 코드는 그대로 쓰지만 학습은 처음부터 다시 합니다. 표를 바꾼 버그 RTL 3종에서 검출까지
  821,299~1,193,152 트랜잭션이 들었습니다.

## 환경

Windows 11, Python 3.14 (흐름 1), YoWASP Yosys 0.69 /
WSL Ubuntu 24.04.5, Python 3.12.3, Icarus Verilog 12.0, cocotb 2.1.0, pyuvm 5.0.0, Yosys 0.33 (흐름 2).
