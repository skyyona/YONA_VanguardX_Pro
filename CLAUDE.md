# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes.  
Based on Andrei Karpathy's vibe-coding principles, adapted by Forrest Chang.  
Merged with YONA VanguardX Pro project-specific rules.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## 5. YONA VanguardX Pro — Project-Specific Rules

### 5-1. No Unsolicited Changes
**사용자 명령 없이 수정·구현 작업은 절대 하지 않는다.**  
Ask first, implement after explicit approval.

### 5-2. No Dummy / Mock / Sample Code
**더미·목업·샘플 코드를 절대 생성하지 않는다.**  
Every line of code written must be production-ready and directly relevant to the request.

### 5-3. Python Version Lock
**Python 3.12.10 단일 버전만 사용한다. 타 버전 설치 절대 금지.**  
Do not suggest, install, or reference any other Python version.

### 5-4. Live Trading Only
**이 앱은 실거래(LIVE) 전용이다. DRY_RUN 구현은 사용자의 의도가 아니다.**  
Do not add dry-run modes, simulation branches, or paper-trading paths unless explicitly requested.

### 5-5. Security — API Credentials
**`bottom/.env`에는 실제 Binance API 자격증명이 포함되어 있다.**  
- Never commit, share, log, or display the contents of `.env`.
- Never echo API keys or secrets in any output.

### 5-6. Syntax Verification
**모든 Python 파일 수정 후 반드시 `python -m py_compile <file>` 구문 검증을 실행한다.**  
Report the result explicitly. Do not mark a task complete without a passing compile check.

### 5-7. Communication
**사용자에게는 항상 존댓말(존경의 존대말)을 사용한다.**

### 5-8. Proof Over Claims
**막연한 완료 보고보다 정확한 테스트를 거친 증거를 보고한다.**

완료 보고 시 반드시 다음 중 하나 이상의 증거를 첨부한다:
- `python -m py_compile <file>` 출력 결과
- 실행 결과 로그 또는 터미널 출력
- 변경 전/후 동작 비교
- 검증에 사용한 명령어와 그 결과

"구현 완료", "수정했습니다" 같은 단언만으로는 보고를 마치지 않는다.  
증거 없는 완료 보고는 완료가 아니다.

### 5-9. No Scope Creep — 요청 범위 초과 구현 금지
**사용자가 명시적으로 요청한 범위를 초과하는 구현은 절대 하지 않는다.**

- 요청된 기능만 구현한다. 관련 있어 보여도 요청하지 않은 것은 추가하지 않는다.
- "이왕이면 이것도" 식의 확장은 반드시 사용자에게 먼저 제안하고 승인을 받은 후 구현한다.
- 구현 전 "이 요청의 정확한 범위는 무엇인가?"를 스스로 확인한다.
- 실거래와 백테스팅은 동일한 전략 범위 내에서 항상 일치해야 한다. 한쪽에만 기능을 추가하면 불일치가 발생한다.

판단 기준: "사용자가 이 기능을 요청했는가?" — No이면 구현하지 않는다.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
