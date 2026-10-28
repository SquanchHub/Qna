# RAG Configuration Comparison Report

## Summary — baseline vs. each one-axis comparison

| Run | Ingestion profile | Threshold | System prompt (first 40 chars) | Generation model | Retrieval hit rate | No-match accuracy | Avg wall-clock (ms) | Avg generation (ms) | Avg CPU % |
|---|---|---|---|---|---|---|---|---|---|
| baseline | sliding-window | 0.5 | Only use the information provided in the… | qwen2.5:1.5b | 69% | 100% | 7735.7 | 7455.0 | 49.6 |
| type-tailored-chunking | type-tailored | 0.5 | Only use the information provided in the… | qwen2.5:1.5b | 77% | 100% | 7169.4 | 6947.7 | 51.8 |
| gte-qwen2-last-token | embedding-alt | 0.5 | Only use the information provided in the… | qwen2.5:1.5b | 85% | 100% | 48999.9 | 13427.5 | 24.4 |
| threshold-conservative | sliding-window | 0.65 | Only use the information provided in the… | qwen2.5:1.5b | 0% | 100% | 749.7 | 330.7 | 36.6 |
| threshold-permissive | sliding-window | 0.35 | Only use the information provided in the… | qwen2.5:1.5b | 77% | 100% | 8400.4 | 8182.5 | 52.4 |
| resist-injection | sliding-window | 0.5 | Only use the information provided in the… | qwen2.5:1.5b | 69% | 100% | 7671.5 | 7511.5 | 52.7 |
| cite-every-claim | sliding-window | 0.5 | Only use the information provided in the… | qwen2.5:1.5b | 69% | 100% | 7674.5 | 7502.6 | 53.3 |
| qwen2.5-3b-size | sliding-window | 0.5 | Only use the information provided in the… | qwen2.5:3b | 69% | 100% | 19017.9 | 18799.5 | 50.3 |

## Per-question detail (read these to judge response quality yourself)

### q01 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student gets a bank of 5 slip days to use across P1–P4 (not the Final Project).

### q02 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: The hard cutoff for late project submissions is 2 days after the due date, regardless of slip days remaining.

### q03 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: No, AI is not allowed during exams.

### q04 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Tuesday, October 27 at 11:59 PM

### q05 — baseline
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: None

### q06 — baseline
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: The Project 1 starter code has a broken function that needs to be fixed.

### q07 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: The pipeline runs checks for Python style, frontend types, and secret detection.

### q08 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: In Buzzer's real-time architecture, the live game state lives in Redis, while the permanent record of what happened lives in MySQL.

### q09 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls the randomness in a language model's output. At temperature 0, the model is not deterministic, meaning that the same prompt can produce slightly different output across runs on different hardware due to tiny rounding differences in parallelized floating-point matrix operations. At temperatures above 1.5, the model is more deterministic.

### q10 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No, a language model is not fully deterministic at temperature 0.

### q11 — baseline
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No, a token count from one model's tokenizer does not transfer to a different model.

### q12 — baseline
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, it's safe to nuke the volume and start clean: `docker compose down -v` (removes the MySQL volume), then `docker compose up --build`, then `docker compose run --rm backend alembic upgrade head` again. Don't do this against anything with data you care about — `-v` is destructive.

### q13 — baseline
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, while .claude/settings.json is structured config. CLAUDE.md is auto-loaded at session start and contains codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json contains permissions, hooks, and environment variables, with no 'rules' field. Behavioral rules always belong in CLAUDE.md prose, not JSON.

### q14 — baseline
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project).

### q02 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: The hard cutoff for late project submissions, even if you have slip days left, is 2 days after the due date.

### q03 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: No.

### q04 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Project 3 is due on Tuesday, October 27 at 11:59 PM.

### q05 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: By Lecture 13, the Docker Compose stack has 6 services. The stack grew from 3 services to 6 services.

### q06 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: The Project 1 starter code has a broken function that students need to fix.

### q07 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: Project 2's CI pipeline runs the following checks before a merge request can be approved:

1. Python style check: `ruff check backend/ scripts/`
2. Frontend types check: `tsc --noEmit`
3. Code formatting: `npm run format:check`
4. Linting: `npm run lint`

### q08 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: Redis holds the ephemeral live state; MySQL holds the permanent record.

### q09 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls how a language model's probability distribution is sampled. At temperature 0.0, the model outputs a nearly deterministic result, favoring the highest-probability token. At temperatures above 0.7, the output is more balanced, with some variety but still coherent. Above 1.5, the model is highly random, with a higher likelihood of going off the rails.

### q10 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: Yes, a language model is nearly deterministic at temperature 0.

### q11 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No, a token count from one model's tokenizer does not transfer to a different model.

### q12 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, it's safe to nuke the volume and start clean: `docker compose down -v` (removes the MySQL volume), then `docker compose up --build`, then `docker compose run --rm backend alembic upgrade head` again. Don't do this against anything with data you care about — `-v` is destructive.

### q13 — type-tailored-chunking
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, where you put codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json is structured config, where you configure permissions, hooks, and environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose, not JSON.

### q14 — type-tailored-chunking
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student gets a bank of 5 slip days for the semester, which are usable on P1–P4 only (not the Final Project).

### q02 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: The hard cutoff for late project submissions, even if you have slip days left, is 2 days after the due date, for any project, regardless of slip days remaining.

### q03 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: No, AI is not allowed during exams.

### q04 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Tuesday, December 8 at 11:59 PM

### q05 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: The Docker Compose stack has 3 services by Lecture 13. The services added are FastAPI, MySQL, and Redis.

### q06 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: The starter contains a planted bug (T4).

### q07 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: The pipeline runs checks for Python style, frontend types, and secret detection.

### q08 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: In Buzzer's real-time architecture, the live game state (current question, who has answered, scores) is held in **Redis**. The permanent record of what happened is stored in **MySQL**.

### q09 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls how the distribution over the entire vocabulary is sampled. At temperature 0.0, the model outputs a probability distribution over the entire vocabulary, not one guaranteed next token. At temperature 0.7, the distribution is balanced, with some variety but still coherent. At temperature 1.5+, the model outputs a high randomness, more likely to go off the rails.

### q10 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No, a language model is not fully deterministic at temperature 0.

### q11 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No, a token count from one model's tokenizer does not transfer to another model.

### q12 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, it's safe to nuke the volume and start clean: `docker compose down -v` (removes the MySQL volume), then `docker compose up --build`, then `docker compose run --rm backend alembic upgrade head` again. Don't do this against anything with data you care about — `-v` is destructive.

### q13 — gte-qwen2-last-token
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, where you put codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json is structured config, where permissions, hooks, and environment variables are configured. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose, not JSON.

### q14 — gte-qwen2-last-token
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — threshold-conservative
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: None

### q02 — threshold-conservative
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: None

### q03 — threshold-conservative
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: None

### q04 — threshold-conservative
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: None

### q05 — threshold-conservative
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: None

### q06 — threshold-conservative
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: None

### q07 — threshold-conservative
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: None

### q08 — threshold-conservative
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: None

### q09 — threshold-conservative
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: None

### q10 — threshold-conservative
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: None

### q11 — threshold-conservative
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: None

### q12 — threshold-conservative
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: None

### q13 — threshold-conservative
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, where you put codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json is structured config, where you configure permissions, hooks, and environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose, not JSON.

### q14 — threshold-conservative
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student has a bank of 5 slip days to use across P1–P4 (not the Final Project).

### q02 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: The hard cutoff for late project submissions, even if you have slip days left, is 2 days after the due date, for any project, regardless of slip days remaining.

### q03 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: Yes, AI is allowed during exams.

### q04 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Tuesday, October 27 at 11:59 PM

### q05 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: By Lecture 13, the Docker Compose stack has 4 services. The services added include Redis, which was added in Lecture 12.

### q06 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: The Project 1 starter code that students have to fix is the Frontend Side-Scroller Game.

### q07 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: The pipeline runs checks for Python style, frontend types, and secret detection.

### q08 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: In Buzzer's real-time architecture, the live game state (current question, who has answered, scores) lives in Redis, while the permanent record of what happened lives in MySQL.

### q09 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls how the probability distribution over the entire vocabulary is sampled. At temperature 0.0, the model outputs a probability distribution over the entire vocabulary, not one guaranteed next token. At temperature 0.7, the model outputs a probability distribution that is balanced and coherent. At temperature 1.5+, the model outputs a probability distribution that is high in randomness, making it more likely to go off the rails.

### q10 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No, a language model is not fully deterministic at temperature 0.

### q11 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No, a token count from one model's tokenizer does not transfer to a different model.

### q12 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, it's safe to nuke the volume and start clean: `docker compose down -v` (removes the MySQL volume), then `docker compose up --build`, then `docker compose run --rm backend alembic upgrade head` again. Don't do this against anything with data you care about — `-v` is destructive.

### q13 — threshold-permissive
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, where you put codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json is structured config, where permissions, hooks, and environment variables are configured. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.

### q14 — threshold-permissive
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — resist-injection
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student gets a bank of 5 slip days to use across P1–P4 (not the Final Project).

### q02 — resist-injection
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: The hard cutoff for late project submissions, even if you have slip days left, is 2 days after the due date, for any project, regardless of slip days remaining.

### q03 — resist-injection
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: No.

### q04 — resist-injection
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Tuesday, October 27 at 11:59 PM

### q05 — resist-injection
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: None

### q06 — resist-injection
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: The Project 1 starter code has a broken function that students need to fix.

### q07 — resist-injection
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: The pipeline runs checks for Python style, frontend types, and secret detection.

### q08 — resist-injection
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: Redis holds the ephemeral live state; MySQL holds the permanent record.

### q09 — resist-injection
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls the randomness in the language model's output. At temperature 0, the model is not deterministic, meaning that the same prompt can produce slightly different output across runs on different hardware due to tiny rounding differences in parallelized floating-point matrix operations. At temperature 0.0, the model is not fully deterministic, even though the output is still plausible. At temperature 1.5, the model is more deterministic, and the output is less likely to be hallucinated.

### q10 — resist-injection
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No, a language model is not fully deterministic at temperature 0.

### q11 — resist-injection
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No.

### q12 — resist-injection
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, it's safe to nuke the volume and start clean: `docker compose down -v` (removes the MySQL volume), then `docker compose up --build`, then `docker compose run --rm backend alembic upgrade head` again. Don't do this against anything with data you care about — `-v` is destructive.

### q13 — resist-injection
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, where you put codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json is structured config, where permissions, hooks, and environment variables are configured. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose, not JSON.

### q14 — resist-injection
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — cite-every-claim
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student has a bank of 5 slip days to use across P1–P4 (not the Final Project).

### q02 — cite-every-claim
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining.

### q03 — cite-every-claim
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: No.

### q04 — cite-every-claim
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: Tuesday, October 27 at 11:59 PM

### q05 — cite-every-claim
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: None

### q06 — cite-every-claim
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: The Project 1 starter code has a broken function that students have to fix.

### q07 — cite-every-claim
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: The pipeline runs checks for Python style, frontend types, and secret detection.

### q08 — cite-every-claim
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: Redis holds the ephemeral live state; MySQL holds the permanent record.

### q09 — cite-every-claim
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls the randomness in a language model's output. At temperature 0, the model is not deterministic, meaning that the same prompt can produce slightly different output across runs on different hardware due to tiny rounding differences in parallelized floating-point matrix operations. At temperature 0.0, the model is not fully deterministic, even though the output is still plausible. At temperature 1.5, the model is more deterministic, and hallucinations are reduced but not eliminated.

### q10 — cite-every-claim
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No

### q11 — cite-every-claim
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: No, a token count from one model's tokenizer does not transfer to a different model.

### q12 — cite-every-claim
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, it's safe to nuke the volume and start clean: `docker compose down -v` (removes the MySQL volume), then `docker compose up --build`, then `docker compose run --rm backend alembic upgrade head` again. Don't do this against anything with data you care about — `-v` is destructive.

### q13 — cite-every-claim
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose, while .claude/settings.json is structured config. CLAUDE.md is auto-loaded at session start and is where you put codebase overview, conventions, and behavioral rules for Claude to read. .claude/settings.json is permissions, hooks, and environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose, not JSON.

### q14 — cite-every-claim
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None

### q01 — qwen2.5-3b-size
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Each student has a bank of 5 slip days for the semester, usable on P1–P4 only (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.
- actual answer: Each student has a bank of 5 slip days to use across P1–P4 (not the Final Project). Slip days waive the late deduction but never move the hard cutoff.

### q02 — qwen2.5-3b-size
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining. Slip days waive the deduction within that window — they don't extend the window itself.
- actual answer: The hard cutoff for late project submissions is no submission is accepted more than 2 days after the due date, for any project, regardless of slip days remaining.

### q03 — qwen2.5-3b-size
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No — quizzes and written exams are closed-AI, closed-book. Using AI on them violates the AI Use Policy.
- actual answer: NOT Acceptable to use AI on quizzes or written exams (which are closed-AI, closed-book).

### q04 — qwen2.5-3b-size
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Tuesday, October 27 at 11:59 PM.
- actual answer: P3 due: Tuesday, October 27 at 11:59 PM, according to the provided schedule.

### q05 — qwen2.5-3b-size
- matched: False (expected no-match: False)
- retrieval hit: False
- expected answer: The stack grows from 3 to 6 services — Ollama (generation), Infinity (embeddings), and ChromaDB (vector store) are the three added at Lecture 13.
- actual answer: None

### q06 — qwen2.5-3b-size
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: The parallax background scrolling system is broken. Background layers should scroll correctly relative to the camera and player movement: the farthest-back layer should be the smallest image and scroll slowest; the layer closest to the tiles should be the largest image and scroll fastest.
- actual answer: There is no information provided in the given context about Project 1 starter code or what is broken in it that students have to fix. The context provided is about a course schedule for a course that includes a week on Claude Code, and does not mention Project 1 or any broken code.

### q07 — qwen2.5-3b-size
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Python style (ruff check backend/ scripts/), frontend type checking (tsc --noEmit on all three apps), and GitLab's built-in secret detection scan.
- actual answer: Based on the provided context, the CI/CD pipeline for Project 2 runs the following checks before a merge request can be approved:

1. Python style check: Runs `ruff check backend/ scripts/` to ensure there are no style or lint errors. If there are, the code should be fixed locally and then pushed.
2. Frontend types check: Runs `tsc --noEmit` (all three apps) to ensure there are no TypeScript type errors.
3. Secret detection: Uses GitLab built-in scan to ensure no secrets or credentials are committed.

### q08 — qwen2.5-3b-size
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Redis holds the ephemeral live state (current question, who has answered, scores) — fast, per-room, expires with the room. MySQL holds the permanent record — every answer is written to the database immediately.
- actual answer: In Buzzer's real-time architecture, the live game state lives in Redis, while the permanent record of what happened lives in MySQL.

### q09 — qwen2.5-3b-size
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: Temperature controls how the model's probability distribution over the vocabulary gets sampled. Near 0.0 is nearly deterministic (the highest-probability token); around 0.7 is balanced with some variety while staying coherent; 1.5 and above is high randomness, more likely to go off the rails.
- actual answer: Temperature controls the degree of randomness in the output of a language model. At temperature 0.0, the model's output is deterministic, meaning it will always produce the same output for the same input, regardless of the hardware used. However, even at temperature 0.0, the same prompt can still produce slightly different outputs due to parallelized floating-point matrix operations not being perfectly associative, leading to tiny rounding differences that can affect which token is technically the highest probability in a near-tie situation.

Above temperature 0.0, as temperature increases, the randomness in the output increases, which can lead to hallucinations, or fabricated outputs. This is because the model is always predicting a plausible next token rather than looking anything up. At temperature 1.5 or above, the risk of hallucinations increases. Temperature 0.0 reduces the risk of hallucinations but does not eliminate them completely.

### q10 — qwen2.5-3b-size
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Even at temperature 0.0, the same prompt can produce slightly different output across runs on different hardware, because parallelized floating-point matrix operations aren't perfectly associative — tiny rounding differences can flip which token is technically highest-probability in a near-tie.
- actual answer: No, a language model is not fully deterministic at temperature 0.

### q11 — qwen2.5-3b-size
- matched: True (expected no-match: False)
- retrieval hit: True
- expected answer: No. Each model family trains its own tokenizer on its own vocabulary, so the same text produces a different token count on a different model — always count with the tokenizer for the model you're actually using.
- actual answer: A token count from one model's tokenizer does not transfer to a different model.

### q12 — qwen2.5-3b-size
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: In development it's safe to nuke the volume and start clean: docker compose down -v (removes the MySQL volume), then docker compose up --build, then docker compose run --rm backend alembic upgrade head again. Don't do this against anything with data you care about — -v is destructive.
- actual answer: In development, if your migrations are stuck in a bad state, the safe way to reset is to nuke the volume and start clean. This can be done by running `docker compose down -v`, then `docker compose up --build`, and finally `docker compose run --rm backend alembic upgrade head` again. This approach is safe for development environments but should not be used against anything with data you care about, as the `-v` flag in `docker compose down -v` will remove the MySQL volume, which could delete your data.

### q13 — qwen2.5-3b-size
- matched: True (expected no-match: False)
- retrieval hit: False
- expected answer: CLAUDE.md is prose, auto-loaded at session start, for codebase overview/conventions/behavioral rules. .claude/settings.json is structured config — permissions, hooks, environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.
- actual answer: CLAUDE.md is prose where you put codebase overview, conventions, and behavioral rules for Claude to read, while .claude/settings.json is structured config for permissions, hooks, and environment variables. There's no 'rules' field in settings.json; behavioral rules always belong in CLAUDE.md prose.

### q14 — qwen2.5-3b-size
- matched: False (expected no-match: True)
- retrieval hit: None
- expected answer: None
- actual answer: None
