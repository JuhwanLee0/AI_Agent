// npm i puppeteer dotenv @google/generative-ai 명령어로 필요한 패키지 설치
const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');
const fsPromises = fs.promises;
const { spawn } = require('child_process');
const { getUserCredentials, buildCookieString, fetchSessionInfo, saveNickName } = require('./lib/utils');
const log = require('./lib/logger');
require('dotenv').config({ path: path.join(__dirname, '.env') });
const { GoogleGenerativeAI } = require('@google/generative-ai');

// 설정 변수
const RUN_MODE = 1;  // 1: 사용자가 종료할때까지 실행, 2: 자동 종료
const HEADLESS_MODE = false;  // false: 브라우저 표시, 'new': 헤드리스 모드

// 상호작용 설정
const useFollow = 1;      // 0: 팔로우 안 함, 1: 팔로우
const useLike = 1;        // 0: 좋아요 안 함, 1: 좋아요
const useRepost = 1;      // 0: 리포스트 안 함, 1: 리포스트
const commentMode = 2;    // 0: 댓글 안 달기, 1: 고정 댓글, 2: AI 댓글
const FRIEND_COMMENT = '좋아요 눌렀어!';  // 고정 댓글 (commentMode=1 일 때 사용)
const AI_MODE = 1;        // 1: Gemini CLI, 2: Codex CLI, 3: Claude CLI, 4: Gemini API, 5: GPT API
const SECOND_AI_MODE = 2; // AI_MODE 실패 시 시도
const GEMINI_MODEL = 'gemini-2.5-flash'; // AI_MODE=4일 때 사용할 Gemini 모델
const GPT_MODEL = 'gpt-4o-mini'; // AI_MODE=5일 때 사용할 GPT 모델
const SPAM_KEYWORDS = ['성인', '19금'];

// 글쓰기 설정
const writePost = 1;      // 0: 아무것도 안 함, 1: 모든 동작 후 포스팅 대기
const uploadImage = 1;    // 0: 이미지 업로드 안 함, 1: 이미지 업로드
const POST_BODY = '안녕하세요!';      // 글쓰기 본문
const POST_TOPIC = '맥북';           // 글쓰기 주제 태그
const POST_IMAGE = path.join(__dirname, 'src', 'imgs', '1.jpg');  // 업로드 이미지
const POST_REPLY = 'https://ttj.kr -> 요기!!';  // 게시 후 답글

// 설치된 크롬 실행 파일 경로 탐지 (macOS / Windows / Linux 지원)
const findChromePath = () => {
  const platform = process.platform;

  const macPaths = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
  ];

  const winPaths = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    process.env.LOCALAPPDATA
      ? path.join(process.env.LOCALAPPDATA, 'Google', 'Chrome', 'Application', 'chrome.exe')
      : '',
  ].filter(Boolean);

  const linuxPaths = [
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
    '/snap/bin/chromium',
  ];

  const candidateMap = { darwin: macPaths, win32: winPaths, linux: linuxPaths };
  const candidates = candidateMap[platform] || linuxPaths;
  const found = candidates.find(p => fs.existsSync(p));

  if (!found) {
    log.warn('설치된 Chrome 없음 — puppeteer 기본 브라우저 사용');
    return undefined;
  }

  log.step(`Chrome: ${found}`);
  return found;
};

// 현재 스크립트의 디렉토리를 사용
const CURRENT_DIR = __dirname;

// 브라우저 프로필 폴더 생성
const createBrowserProfileDir = async (id) => {
  const profileDir = path.join(CURRENT_DIR, 'browser_profile', `${id}_browser_profile`);

  try {
    if (!fs.existsSync(profileDir)) {
      await fsPromises.mkdir(profileDir, { recursive: true });
      log.step(`프로필 폴더 생성: ${path.basename(profileDir)}`);
    }
    return profileDir;
  } catch (error) {
    log.err(`프로필 폴더 생성 실패: ${error.message}`);
    return null;
  }
};

// Chrome 프로필에 남은 비정상 종료 상태를 정리해 세션 복구/충돌 경고를 줄인다.
const normalizeChromeProfileState = async (profileDir) => {
  const targets = [
    path.join(profileDir, 'Default', 'Preferences'),
    path.join(profileDir, 'Local State'),
  ];

  for (const filePath of targets) {
    try {
      if (!fs.existsSync(filePath)) continue;

      const raw = await fsPromises.readFile(filePath, 'utf8');
      const data = JSON.parse(raw);

      if (filePath.endsWith('Preferences')) {
        data.exit_type = 'Normal';
        data.exited_cleanly = true;
        if (data.profile && typeof data.profile === 'object') data.profile.exit_type = 'Normal';
        if (data.sessions && Array.isArray(data.sessions.event_log)) {
          data.sessions.event_log = data.sessions.event_log.map(event =>
            event && event.crashed === true ? { ...event, crashed: false } : event
          );
        }
      } else {
        data.exited_cleanly = true;
        if (data.profile?.info_cache) {
          for (const key of Object.keys(data.profile.info_cache)) {
            data.profile.info_cache[key].active_time = data.profile.info_cache[key].active_time || Math.floor(Date.now() / 1000);
          }
        }
        if (data.user_experience_metrics?.stability) data.user_experience_metrics.stability.exited_cleanly = true;
      }

      await fsPromises.writeFile(filePath, JSON.stringify(data));
    } catch (error) {
      log.warn(`프로필 상태 정리 실패 (${path.basename(filePath)}): ${error.message}`);
    }
  }
};

// 지정한 범위 안에서 랜덤한 시간만큼 기다린다
const randomDelay = async (min, max) =>
  new Promise(resolve => setTimeout(resolve, Math.random() * (max - min) + min));

// 정확히 지정된 시간(ms)만큼 기다린다
const delay = (time) =>
  new Promise(resolve => setTimeout(resolve, time));

// ── Gemini AI 댓글 생성 ──────────────────────────────────────────
// 텍스트에서 이모지를 모두 제거한다
const removeEmojis = (text) =>
  text.replace(/([\u2700-\u27BF]|[\uE000-\uF8FF]|\uD83C[\uDC00-\uDFFF]|\uD83D[\uDC00-\uDFFF]|[\u2011-\u26FF]|\uD83E[\uDD10-\uDDFF])/g, '');

// \uD14D\uC2A4\uD2B8\uC5D0\uC11C \uB9C8\uD06C\uB2E4\uC6B4 \uAE30\uD638(*, #, ` \uB4F1)\uB97C \uC81C\uAC70\uD55C\uB2E4
const removeMarkdown = (text) =>
  text
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\*(.*?)\*/g, '$1')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1')
    .replace(/^#+\s*/gm, '')
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^[-*+]\s/gm, '')
    .replace(/^\d+\.\s/gm, '')
    .replace(/^>\s*/gm, '')
    .trim();

// AI에게 게시글 안전성 검사와 댓글 생성을 함께 요청하는 프롬프트를 만든다
const buildAnalysisPrompt = (postContent) =>
  `아래 Threads 게시물을 먼저 안전성 검사해줘.
다음 중 하나라도 해당하면 {"use":false,"content":"거절사유를 한국어로 한 줄"} 형식으로 응답해:
- 특정인과의 직접 만남, 동행, 모임 참여 등을 독자에게 직접 요청하거나 댓글/연락을 유도하는 내용 (단순 장소/음식/경험 추천이나 일상 공유는 해당 안 됨)
- 신청서 작성, 지원서 제출 등 특정 행동을 요구하는 내용
- 혐오, 학대, 폭력, 성인/음란 관련 내용
- 스팸, 사기성 내용
- 그 외 올바르지 않다고 판단되는 내용

위에 해당하지 않는 정상적인 게시물이면:
게시물의 언어를 감지해서 반드시 그 언어로만 짧고 자연스러운 댓글을 작성해줘. 재미있고 긍정적이며 센스있게, 상대방 호칭 없이.
country_lang 값은 감지된 언어명으로: "한국어", "english", "japan", "chinese", "spanish" (그 외도 해당 언어명).
content는 반드시 country_lang 언어로만 작성. 절대 다른 언어 섞지마.
반드시 아래 JSON 형식으로만 응답해. 다른 텍스트 절대 포함하지마.
{"use":true,"country_lang":"한국어","content":"여기에 답변 내용"}
게시물: "${postContent}"`;

// AI에게 게시글 댓글만 생성하도록 요청하는 프롬프트를 만든다
const buildGeminiPrompt = (postContent) =>
  `다음 Threads 게시물에 대한 답변을 작성해줘. 나는 20대 남자이고, 상대방이 사용한 국가 언어와 동일한 국가 언어로 답변할거야. 재미있고 긍정적이며 센스있게 짧게 반말로 예의있게 답변해줘. 상대방 호칭은 부르지마. "${postContent}"`;

// AI 응답에서 불필요한 문자(이모지, 마크다운, 따옴표 등)를 정리한다
const cleanResponse = (text) =>
  removeMarkdown(removeEmojis(text)).replace(/^응답:\s*/i, '').trim().replace(/^["'"""'']|["'"""'']$/g, '').trim();

const previewText = (text, max = 1000) => (text || '').trim().replace(/\r/g, '').slice(0, max);
const isGeminiQuotaError = (text) => /exhausted your capacity on this model|quota/i.test(text || '');
const isClaudeQuotaError = (text) => /monthly usage limit|usage limit|rate limit|quota|too many requests/i.test(text || '');

// AI가 반환한 텍스트에서 첫 번째 JSON 객체를 찾아 파싱 가능한 후보로 추출한다
const extractJsonCandidate = (raw) => {
  const text = (raw || '').trim();
  if (!text) return null;

  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const source = fenced ? fenced[1].trim() : text;

  if (source.startsWith('{') && source.endsWith('}')) return source;

  let depth = 0;
  let start = -1;

  for (let i = 0; i < source.length; i += 1) {
    const char = source[i];
    if (char === '{') {
      if (depth === 0) start = i;
      depth += 1;
    } else if (char === '}') {
      if (depth === 0) continue;
      depth -= 1;
      if (depth === 0 && start !== -1) return source.slice(start, i + 1);
    }
  }

  return null;
};

// AI 응답 텍스트를 분석 결과 객체로 안전하게 변환한다
const parseAnalysisResponse = (raw) => {
  const candidate = extractJsonCandidate(raw);
  if (!candidate) return null;

  try {
    const parsed = JSON.parse(candidate);
    const content = cleanResponse(parsed.content || '');
    const countryLang = cleanResponse(parsed.country_lang || '') || 'unknown';

    if (parsed.use === true && !content) return null;

    return {
      use: parsed.use === true,
      country_lang: countryLang,
      content,
    };
  } catch (error) {
    return null;
  }
};

// Windows에서 gemini.cmd는 shell 경유 시 멀티라인 프롬프트가 잘릴 수 있어 JS 엔트리포인트를 직접 실행한다.
const getGeminiCLICommand = () => {
  if (process.platform !== 'win32') return { cmd: 'gemini', args: [], shell: false };

  const entry = path.join(process.env.APPDATA || '', 'npm', 'node_modules', '@google', 'gemini-cli', 'dist', 'index.js');
  if (fs.existsSync(entry)) return { cmd: 'node', args: [entry], shell: false };

  return { cmd: 'gemini.cmd', args: [], shell: true };
};

// 터미널 명령어(gemini CLI)로 Gemini AI를 호출한다
const callGeminiCLI = (prompt) =>
  new Promise((resolve, reject) => {
    const cli = getGeminiCLICommand();
    const proc = spawn(cli.cmd, [...cli.args, prompt], { shell: cli.shell });
    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', d => { stdout += d.toString(); });
    proc.stderr.on('data', d => { stderr += d.toString(); });
    proc.on('close', code => {
      if (code !== 0) {
        const stdoutPreview = previewText(stdout);
        const stderrPreview = previewText(stderr);
        if (isGeminiQuotaError(`${stdoutPreview}\n${stderrPreview}`)) {
          log.warn('Gemini CLI 한도 초과');
          reject(new Error('Gemini CLI 한도 초과'));
          return;
        }
        if (stdoutPreview) log.warn(`Gemini CLI stdout 원본: ${stdoutPreview}`);
        if (stderrPreview) log.warn(`Gemini CLI stderr 원본: ${stderrPreview}`);
        reject(new Error(`CLI 실패 (exit ${code}) | stdout: ${stdoutPreview || '(empty)'} | stderr: ${stderrPreview || '(empty)'}`));
      }
      else resolve(stdout.trim());
    });
    proc.on('error', reject);
  });

// OpenAI Codex CLI로 AI를 호출한다
const callCodexCLI = (prompt) =>
  new Promise((resolve, reject) => {
    const cmd = process.platform === 'win32' ? 'codex.cmd' : 'codex';
    const proc = spawn(cmd, ['exec', '--skip-git-repo-check', '-'], { shell: process.platform === 'win32', stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', d => { stdout += d.toString(); });
    proc.stderr.on('data', d => { stderr += d.toString(); });
    proc.on('close', code => {
      if (code !== 0) {
        const stdoutPreview = previewText(stdout);
        const stderrPreview = previewText(stderr);
        if (stdoutPreview) log.warn(`Codex CLI stdout 원본: ${stdoutPreview}`);
        if (stderrPreview) log.warn(`Codex CLI stderr 원본: ${stderrPreview}`);
        reject(new Error(`Codex CLI 실패 (exit ${code}) | stdout: ${stdoutPreview || '(empty)'} | stderr: ${stderrPreview || '(empty)'}`));
      }
      else resolve(stdout.trim());
    });
    proc.stdin.write(prompt);
    proc.stdin.end();
    proc.on('error', reject);
  });

// Claude CLI로 AI를 호출한다
const callClaudeCLI = (prompt) =>
  new Promise((resolve, reject) => {
    const cmd = process.platform === 'win32' ? 'claude.cmd' : 'claude';
    const proc = spawn(cmd, ['-p', '--output-format', 'text'], {
      shell: process.platform === 'win32',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', d => { stdout += d.toString(); });
    proc.stderr.on('data', d => { stderr += d.toString(); });
    proc.on('close', code => {
      if (code !== 0) {
        const stdoutPreview = previewText(stdout);
        const stderrPreview = previewText(stderr);
        if (isClaudeQuotaError(`${stdoutPreview}\n${stderrPreview}`)) {
          log.warn('토큰을 다 써서 리밋걸림');
          reject(new Error('Claude CLI 한도 초과'));
          return;
        }
        if (stdoutPreview) log.warn(`Claude CLI stdout 원본: ${stdoutPreview}`);
        if (stderrPreview) log.warn(`Claude CLI stderr 원본: ${stderrPreview}`);
        reject(new Error(`Claude CLI 실패 (exit ${code}) | stdout: ${stdoutPreview || '(empty)'} | stderr: ${stderrPreview || '(empty)'}`));
        return;
      }
      resolve(stdout.trim());
    });
    proc.stdin.write(prompt);
    proc.stdin.end();
    proc.on('error', reject);
  });

// API 방식으로 Gemini AI를 호출한다
const callGeminiAPI = async (prompt) => {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) throw new Error('GEMINI_API_KEY가 .env에 없습니다.');
  const genAI = new GoogleGenerativeAI(apiKey);
  const model = genAI.getGenerativeModel({
    model: GEMINI_MODEL,
    generationConfig: { temperature: 1, topP: 0.95, topK: 64, maxOutputTokens: 8192 },
  });
  const result = await model.startChat({ history: [] }).sendMessage(prompt);
  return result.response.text();
};

// GPT API로 AI를 호출한다 (AI_MODE=5, .env에 OPENAI_API_KEY 필요)
const callGPTAPI = async (prompt) => {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) throw new Error('OPENAI_API_KEY가 .env에 없습니다.');
  const axios = require('axios');
  const response = await axios.post('https://api.openai.com/v1/chat/completions', {
    model: GPT_MODEL,
    messages: [{ role: 'user', content: prompt }],
    max_tokens: 8192,
    temperature: 0.7,
  }, {
    headers: { 'Authorization': `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    timeout: 120000,
  });
  return response.data?.choices?.[0]?.message?.content || '';
};

// 모드 번호에 해당하는 AI 호출 함수를 반환한다
const getAICaller = (mode) => {
  if (mode === 1) return callGeminiCLI;
  if (mode === 2) return callCodexCLI;
  if (mode === 3) return callClaudeCLI;
  if (mode === 4) return callGeminiAPI;
  if (mode === 5) return callGPTAPI;
  return callGeminiCLI;
};

// AI_MODE로 호출하고 실패 시 SECOND_AI_MODE로 재시도한다
const callAI = async (prompt) => {
  try {
    return await getAICaller(AI_MODE)(prompt);
  } catch (e) {
    if (SECOND_AI_MODE === 0) throw e;
    log.warn(`AI_MODE=${AI_MODE} 실패 — SECOND_AI_MODE=${SECOND_AI_MODE} 재시도`);
    return getAICaller(SECOND_AI_MODE)(prompt);
  }
};

// AI를 이용해 댓글을 생성한다
const generateGeminiComment = async (postContent) => {
  const prompt = buildGeminiPrompt(postContent);
  const text = await callAI(prompt);
  return cleanResponse(text);
};

// 설정된 모드에 따라 적절한 댓글(고정 또는 AI 생성)을 가져온다
const getComment = async (postContent) => {
  if (commentMode === 0) return null;
  if (commentMode === 1) return FRIEND_COMMENT;
  log.step('AI 댓글 생성 중...');
  try {
    return await generateGeminiComment(postContent);
  } catch (e) {
    return FRIEND_COMMENT;
  }
};

// 게시글을 분석해 적합한지 판단하고, 적합하면 AI 댓글까지 함께 만든다
const analyzeAndComment = async (postContent) => {
  if (!postContent.trim()) return { use: false, country_lang: 'unknown', content: '빈 게시글' };

  const spamHit = SPAM_KEYWORDS.find(kw => postContent.includes(kw));
  if (spamHit) return { use: false, country_lang: 'unknown', content: `스팸 키워드: ${spamHit}` };

  const prompt = buildAnalysisPrompt(postContent);
  try {
    const raw = await callAI(prompt);
    const parsed = parseAnalysisResponse(raw);
    if (parsed) return parsed;
    log.warn(`AI 응답 파싱 실패 — 건너뜀 | raw: ${previewText(raw, 300) || '(empty)'}`);
    return { use: false, country_lang: 'unknown', content: 'AI 응답 파싱 실패' };
  } catch (e) {
    log.warn(`콘텐츠 분석 실패 (${e.message}) — 건너뜀`);
  }
  return { use: false, country_lang: 'unknown', content: 'AI 호출 실패' };
};
// ────────────────────────────────────────────────────────────────

// 재귀 기반 스크롤 (사이드이펙트는 page 호출 경계에 한정)
const scrollDown = async (page, times, current = 0) => {
  if (current >= times) return;
  await page.evaluate(() => window.scrollBy(0, window.innerHeight));
  await delay(2000);
  return scrollDown(page, times, current + 1);
};

// 재귀 기반 사람처럼 타이핑
const typeChar = async (page, selector, chars, idx = 0) => {
  if (idx >= chars.length) return;
  await page.type(selector, chars[idx], { delay: Math.random() * 150 + 50 });
  await randomDelay(10, 100);
  return typeChar(page, selector, chars, idx + 1);
};

// 사람이 직접 입력하는 것처럼 텍스트를 한 글자씩 타이핑한다
const typeHumanLike = async (page, selector, text) => {
  await page.focus(selector);
  await typeChar(page, selector, [...text]);
};

// ── 게시 버튼 셀렉터 헬퍼 (page.evaluate 내부에서 실행 가능하도록 함수 본문만 전달) ──
// 클래스 'x15zctf7'를 가진 부모 컨테이너 내부의 '게시' 버튼 탐색
const findPostButtonInPage = () =>
  Array.from(document.querySelectorAll('[role="button"]'))
    .find(b =>
      b.textContent.trim() === '게시' &&
      b.parentElement?.parentElement?.className?.includes('x15zctf7')
    );

// 좋아요 클릭 (사이드이펙트: page 조작 + console)
const clickLike = async (page) => {
  const likeClicked = await page.evaluate(() => {
    const el = document.querySelector('svg[aria-label="좋아요"]')?.closest('[role="button"]') ||
      document.querySelector('svg[aria-label="좋아요"]')?.closest('div');
    if (!el) return false;
    el.click();
    return true;
  });
  log.action('❤️ ', '좋아요', likeClicked);
  await delay(1000);
};

// 리포스트 클릭 (메뉴 열기 → "리포스트" 메뉴 항목 클릭)
const clickRepost = async (page) => {
  const repostClicked = await page.evaluate(() => {
    // aria-haspopup="dialog" 버튼이 리포스트 버튼 (SVG aria-label 없음)
    const el = document.querySelector('[aria-haspopup="dialog"][role="button"]');
    if (!el) return false;
    el.click();
    return true;
  });

  if (!repostClicked) {
    log.action('🔁', '리포스트', false);
    await delay(1000);
    return;
  }

  await delay(800);
  // 팝업 메뉴에서 role="menuitem" 중 텍스트 "리포스트" 클릭
  const repostConfirmed = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('[role="menuitem"]'))
      .find(el => el.textContent.includes('리포스트'));
    if (!btn) return false;
    btn.click();
    return true;
  });
  log.action('🔁', '리포스트', repostConfirmed);
  await delay(1000);
};

// 댓글 게시
const postComment = async (page, comment) => {
  // 답글 버튼 클릭 → 댓글 입력창 열기
  await page.evaluate(() => {
    const el = document.querySelector('svg[aria-label="답글"]')?.closest('[role="button"]') ||
      document.querySelector('svg[aria-label="답글"]')?.closest('div');
    if (el) el.click();
  });
  await delay(1500);

  // 댓글 입력 (contenteditable focus 후 keyboard.type)
  const inputHandle = await page.$('div[contenteditable="true"]');
  if (!inputHandle) {
    log.action('💬', '댓글', false, '입력창 없음');
    await delay(1500);
    return;
  }

  await page.evaluate(el => el.focus(), inputHandle);
  await delay(300);
  await page.keyboard.type(comment, { delay: 80 });
  await delay(500);
  await randomDelay(3000, 5000);

  // 게시 버튼 클릭 (단일 '게시' 텍스트 매칭 — 댓글 모달 컨텍스트)
  const posted = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('[role="button"]'))
      .find(b => b.textContent.trim() === '게시');
    if (!btn) return false;
    btn.click();
    return true;
  });
  log.action('💬', '댓글', posted, posted ? `"${comment.substring(0, 40)}"` : '');
  await delay(1500);
};

// 게시글 좋아요 + 리포스트 + 댓글 달기 — 선언형 파이프라인
const interactWithPost = async (page, postUrl, comment) => {
  await page.goto(postUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await delay(2000);

  const actions = [
    { enabled: useLike === 1, fn: () => clickLike(page) },
    { enabled: useRepost === 1, fn: () => clickRepost(page) },
    { enabled: comment !== null, fn: () => postComment(page, comment) },
  ].filter(a => a.enabled);

  await actions.reduce((p, { fn }) => p.then(fn), Promise.resolve());
};

// 특정 유저 프로필에서 최신 게시글 URL 목록을 수집한다
const scrapeUserPosts = async (page, userUrl) => {
  await page.goto(userUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await delay(2000);
  return page.evaluate(() => {
    return [...new Set(
      Array.from(document.querySelectorAll('a[href]'))
        .map(a => a.getAttribute('href'))
        .filter(href => href.includes('/post/') && !href.includes('/media'))
    )].map(href => 'https://www.threads.net' + href);
  });
};

// 탐색 피드에서 아직 팔로우하지 않은 유저 목록을 수집한다
const scrapeThreadsFeed = async (page, myNickName) => {
  await page.waitForSelector('a[href^="/@"]', { timeout: 10000 }).catch(() => { });

  return page.evaluate((myNickName) => {
    const cards = Array.from(document.querySelectorAll('div[data-pressable-container="true"]'));

    // 팔로우 버튼에서 출발해 조상 8단계 내에서 유저링크를 찾는다
    const findUserForButton = (btn) => {
      let el = btn.parentElement;
      for (let i = 0; i < 8; i++) {
        if (!el) return null;
        const link = Array.from(el.querySelectorAll('a[href^="/@"]'))
          .find(a => !a.getAttribute('href').includes('/post/'));
        if (link) return link.getAttribute('href').replace(/^\/@/, '');
        el = el.parentElement;
      }
      return null;
    };

    return cards.reduce((results, card) => {
      // 카드 내 모든 팔로우/팔로잉 버튼을 순회
      const followBtns = Array.from(card.querySelectorAll('[role="button"], button'))
        .filter(b => ['팔로우', '팔로잉'].includes(b.textContent.trim()));

      return followBtns.reduce((acc, btn) => {
        if (btn.textContent.trim() === '팔로잉') return acc;

        const userName = findUserForButton(btn);
        if (!userName) return acc;
        if (myNickName && userName === myNickName) return acc;
        if (acc.some(r => r.userName === userName)) return acc;

        const userUrl = 'https://www.threads.net/@' + userName;
        return [...acc, { userName, userUrl }];
      }, results);
    }, []);
  }, myNickName);
};

// 사용자가 직접 로그인할 때까지 기다린다
const waitForManualLogin = async (page) => {
  await page.goto('https://www.threads.net/', { waitUntil: 'domcontentloaded', timeout: 60000 });

  // 3초마다 닉네임 감지 시도 (닉네임 = 로그인 완료 신호)
  const pollNickName = async () => {
    try {
      const cookies = await page.cookies();
      const cookieString = buildCookieString(cookies);
      const { nickName } = await fetchSessionInfo(cookieString);
      if (nickName) return nickName;
    } catch (e) {}
    await delay(3000);
    return pollNickName();
  };

  // 이미 로그인된 상태인지 즉시 확인
  try {
    const cookies = await page.cookies();
    const cookieString = buildCookieString(cookies);
    const { nickName } = await fetchSessionInfo(cookieString);
    if (nickName) { log.ok('이미 로그인됨'); return; }
  } catch (e) {}

  log.info('브라우저에서 직접 로그인해주세요. 완료되면 자동으로 진행됩니다...');
  await pollNickName();
  log.ok('로그인 감지됨 — 자동화를 시작합니다');
};

// 현재 유저 프로필 페이지에서 팔로우 버튼을 클릭한다
const followOnProfile = async (page) => {
  // 프로필 페이지에서 이미 팔로우 중인지 재확인 (피드 카드 미스매치 방지)
  const alreadyFollowing = await page.evaluate(() =>
    Array.from(document.querySelectorAll('[role="button"]'))
      .some(b => ['팔로잉', '팔로잉 중', 'Following'].includes(b.textContent.trim()))
  );
  if (alreadyFollowing) {
    log.action('➕', '팔로우', false, '이미 팔로우 중 — 건너뜀');
    return;
  }

  const followed = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('[role="button"]'))
      .find(b => b.textContent.trim() === '팔로우');
    if (!btn) return false;
    btn.click();
    return true;
  });
  log.action('➕', '팔로우', followed);
  await delay(1500);

  const mutualClicked = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('[role="button"]'))
      .find(b => b.textContent.trim() === '맞팔로우');
    if (!btn) return false;
    btn.click();
    return true;
  });
  if (mutualClicked) { log.action('🤝', '맞팔로우', true); await delay(1000); }
};

// 게시글이 없을 때 사용할 AI 결과 기본값을 만든다
const buildNoPostAiResult = () => ({
  postContent: '',
  ai_use: null,
  ai_lang: '',
  ai_comment: '',
  ai_skip_reason: '',
});

// 댓글 모드에 따라 적절한 AI 분석을 시작한다
const buildAnalysisForMode = async (mode, postContent) => {
  if (mode === 0) return { use: null, country_lang: null, content: null };
  const result = await analyzeAndComment(postContent);
  if (mode === 1) return { ...result, content: result.use ? FRIEND_COMMENT : result.content };
  return result;
};

// AI 분석 결과를 저장용 객체 형식으로 변환한다
const buildAiResult = ({ mode, postContent, analysis }) => ({
  postContent,
  ai_use: analysis.use,
  ai_lang: analysis.country_lang,
  ai_comment: mode === 0 ? null : analysis.use ? analysis.content : '',
  ai_skip_reason: mode === 0 ? null : analysis.use === false ? analysis.content : '',
});

// 유저 정보와 AI 분석 결과를 합쳐 저장할 최종 레코드를 만든다
const buildResultRecord = ({ userWithPost, aiResult, mode, now }) => ({
  ...userWithPost,
  ...aiResult,
  ai_at: mode === 0 ? null : now,
});

const saveResultRecord = async (resultPath, record) => {
  await fsPromises.writeFile(resultPath, JSON.stringify([record], null, 2), 'utf8');
  log.divider();
  log.ok('result.json 저장');
};

// AI 판단 결과를 터미널에 출력한다
const logAnalysisResult = ({ mode, analysis }) => {
  if (mode === 0) {
    log.step('AI 판단 없음');
    return;
  }
  log.step(`언어: ${analysis.country_lang}${!analysis.use ? ` | 건너뜀: ${analysis.content}` : ''}`);
};

// AI 판단에 따라 댓글을 게시할지 건너뛸지를 결정한다
const handleCommentFromAnalysis = async (page, mode, analysis) => {
  if (analysis.use === false) {
    log.warn(`게시글 건너뜀 — ${analysis.content}`);
    return;
  }
  if (mode !== 0 && analysis.content) await postComment(page, analysis.content);
};

// 1단계: AI 분석만 수행 (게시글 페이지로 이동 + 본문 스크랩 + AI 판단)
const analyzePostContent = async (page, postUrl, mode) => {
  log.post(postUrl);
  await page.goto(postUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await delay(1500);
  const postContent = await scrapePostContentInPlace(page);
  const analysis = await buildAnalysisForMode(mode, postContent);
  logAnalysisResult({ mode, analysis });
  return { postContent, analysis };
};

// 2단계: AI 통과 후 액션 수행 (게시글 페이지에 있는 상태에서 호출)
const performPostActions = async (page, mode, analysis) => {
  if (useLike === 1) await clickLike(page);
  if (useRepost === 1) await clickRepost(page);
  await handleCommentFromAnalysis(page, mode, analysis);
};

// 재귀로 다음 유저 시도 — AI 부적합 판단 시 자동으로 다음 유저로 넘어감
const tryNextUser = async (page, users, idx, resultPath) => {
  if (idx >= users.length) {
    log.warn('적합한 게시글을 찾지 못했습니다 (모든 유저 필터링됨)');
    return;
  }

  const user = users[idx];
  log.user(user.userName);

  const postUrls = await scrapeUserPosts(page, user.userUrl);
  const newPostUrl = postUrls[0] || null;

  if (!newPostUrl) {
    log.warn('게시글 없음 — 다음 유저로');
    return tryNextUser(page, users, idx + 1, resultPath);
  }

  const { postContent, analysis } = await analyzePostContent(page, newPostUrl, commentMode);
  const userWithPost = { ...user, postUrl: newPostUrl };
  const aiResult = buildAiResult({ mode: commentMode, postContent, analysis });
  const record = buildResultRecord({
    userWithPost,
    aiResult,
    mode: commentMode,
    now: new Date().toISOString(),
  });

  await saveResultRecord(resultPath, record);

  // analysis.use === false이면 skip (null이면 commentMode===0이므로 통과)
  if (analysis.use === false) {
    log.warn(`건너뜀 — 다음 유저로 (${analysis.content})`);
    return tryNextUser(page, users, idx + 1, resultPath);
  }

  // 통과 → 프로필 페이지로 이동 후 팔로우
  if (useFollow === 1) {
    await page.goto(user.userUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await delay(1500);
    await followOnProfile(page);
  }

  // 게시글 페이지로 돌아가서 좋아요·리포스트·댓글
  await page.goto(newPostUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await delay(1500);
  await performPostActions(page, commentMode, analysis);
};

// 피드에서 유저를 찾아 팔로우와 좋아요, 댓글까지 전체 흐름을 실행한다
const processFriendshipMode = async (page) => {
  log.section('피드 크롤링');
  await page.goto('https://www.threads.net/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await delay(2000);

  await page.waitForSelector('a[href="/search"]', { timeout: 10000 });
  await page.click('a[href="/search"]');
  await delay(3000);

  await scrollDown(page, 1);

  const myNickName = process.env.NICK_NAME || '';
  const scraped = await scrapeThreadsFeed(page, myNickName);
  log.ok(`유저 ${scraped.length}명 발견`);

  if (!scraped.length) { log.warn('새로운 유저 없음'); return; }

  const resultPath = path.join(__dirname, 'result.json');
  await tryNextUser(page, scraped, 0, resultPath);
};

// 게시글 본문 텍스트 수집 (goto 없는 버전 — 이미 게시글 페이지에 있을 때 사용)
const scrapePostContentInPlace = async (page) => {
  const postContent = await page.evaluate(() => {
    // 첫 번째 컨테이너만 선택 (댓글 제외, 본문만)
    const container = document.querySelector('div[class*="x1a6qonq"]');
    if (!container) return '';
    const spans = Array.from(container.querySelectorAll('span[dir="auto"] > span'));
    return spans.map(el => el.innerText.trim()).filter(t => t).join('\n');
  });
  const preview = postContent.replace(/\n/g, ' ').substring(0, 60);
  log.step(`본문: "${preview}${postContent.length > 60 ? '…' : ''}"`);
  return postContent;
};

// 게시글 본문 텍스트 수집 (goto 포함 — 하위 호환)
const scrapePostContent = async (page, postUrl) => {
  await page.goto(postUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await delay(1500);
  return scrapePostContentInPlace(page);
};

// ── main 분해 함수들 ──────────────────────────────────────────────

// 브라우저 인스턴스 생성
const initBrowser = async (profileDir, extensions) => {
  const chromePath = findChromePath();
  const browserOptions = {
    headless: HEADLESS_MODE,
    ignoreHTTPSErrors: true,
    ...(chromePath ? { executablePath: chromePath } : {}),
    defaultViewport: null,
    userDataDir: profileDir,
    args: [
      "--disable-automation",
      "--disable-blink-features=AutomationControlled",
      "--hide-crash-restore-bubble",
      "--disable-session-crashed-bubble",
      "--disable-features=InfiniteSessionRestore",
      "--start-maximized",
      "--lang=ko-KR,ko",
      "--enable-extensions",
      ...(process.platform === 'linux' ? ["--no-sandbox", "--disable-setuid-sandbox"] : []),
      ...extensions,
    ],
    env: {
      ...process.env,
      LANG: 'ko_KR.UTF-8'
    }
  };

  log.section('브라우저 시작');
  log.step(`프로필: ${path.basename(profileDir)}`);
  return puppeteer.launch(browserOptions);
};

// 페이지 환경 설정 (viewport, webdriver, headers, geolocation, timezone, dialog)
const setupPage = async (page) => {
  // viewport
  const viewport = await page.evaluate(() => ({
    width: window.innerWidth || window.screen.availWidth,
    height: window.innerHeight || window.screen.availHeight,
  }));
  await page.setViewport({ width: viewport.width, height: viewport.height });

  // webdriver 숨기기
  await page.evaluateOnNewDocument(() => {
    Object.defineProperty(navigator, "webdriver", {
      get: () => false,
    });
  });

  // 나가기 얼럿 자동 수락 (beforeunload 다이얼로그)
  page.on('dialog', async (dialog) => {
    await dialog.accept();
  });

  // 한국 로케일 및 언어 설정
  await page.setExtraHTTPHeaders({
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
  });

  // 지리적 위치 설정 (서울)
  await page.evaluateOnNewDocument(() => {
    const mockGeolocation = {
      latitude: 37.5665,
      longitude: 126.9780,
      accuracy: 100
    };

    navigator.geolocation.getCurrentPosition = (cb) => {
      cb({ coords: mockGeolocation });
    };
  });

  // 한국 표준시 설정
  await page.emulateTimezone('Asia/Seoul');
};

// 로그인 후 닉네임 확인/저장 (실패 시 경고만 출력)
const ensureSession = async (page) => {
  try {
    const cookies = await page.cookies();
    const cookieString = buildCookieString(cookies);
    const { nickName: freshNick } = await fetchSessionInfo(cookieString);
    if (freshNick) {
      await saveNickName(freshNick);
      log.ok(`닉네임: ${freshNick}`);
      return;
    }
    log.warn('닉네임 미감지 — NICK_NAME 환경변수 사용');
  } catch (error) {
    log.warn(`세션 확인 오류 (${error.message})`);
  }
};

// 상호작용 단계 실행
const runInteractions = async (page) => {
  const hasAnyInteraction = useFollow === 1 || useLike === 1 || useRepost === 1 || commentMode !== 0;
  if (hasAnyInteraction) {
    await processFriendshipMode(page);
    return;
  }
  log.info('모든 상호작용 비활성화 — 피드 크롤링 건너뜀');
};

// ── 포스팅 분해 함수들 ──────────────────────────────────────────

// 만들기(포스팅) 버튼 클릭
const openComposeModal = async (page) => {
  await page.goto('https://www.threads.net/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await delay(1500);
  const postBtnClicked = await page.evaluate(() => {
    const el = document.querySelector('svg[aria-label="만들기"]')?.closest('[role="button"]');
    if (!el) return false;
    el.click();
    return true;
  });
  log.action('📝', '작성열기', postBtnClicked);

  // 글쓰기 모달 대기
  await page.waitForSelector('div[contenteditable="true"][data-lexical-editor="true"]', { timeout: 10000 })
    .catch(() => log.warn('글쓰기 입력창 없음'));
  await delay(500);
};

// 주제 추가
const setPostTopic = async (page, topic) => {
  const topicInput = await page.$('input[placeholder="주제 추가"]');
  if (!topicInput) {
    log.action('🏷️ ', '주제', false, '입력창 없음');
    await delay(300);
    return;
  }
  await page.evaluate(el => el.focus(), topicInput);
  await delay(300);
  await page.keyboard.type(topic, { delay: 80 });
  await page.waitForSelector('li[role="option"] div[role="none"]', { timeout: 5000 })
    .catch(() => { });
  const firstOption = await page.$('li[role="option"] div[role="none"]');
  if (firstOption) {
    await page.evaluate(el => el.click(), firstOption);
  }
  log.action('🏷️ ', '주제', !!firstOption, topic);
  await delay(300);
};

// 본문 입력 + (URL 시) OG 카드 대기
const setPostBody = async (page, body) => {
  const editor = await page.$('div[contenteditable="true"][data-lexical-editor="true"]');
  if (!editor) return;
  await page.evaluate((text) => {
    const el = document.querySelector('div[contenteditable="true"][data-lexical-editor="true"]');
    el.focus();
    document.execCommand('insertText', false, text);
  }, body);

  // URL 포함 시 OG 카드 로딩 대기
  if (/https?:\/\//.test(body)) {
    await page.waitForSelector('a[rel="nofollow noreferrer"] img', { timeout: 10000 })
      .then(() => log.step('OG 카드 감지'))
      .catch(() => log.step('OG 카드 미감지'));
  }
};

// 이미지 업로드
const attachPostImage = async (page, imagePath) => {
  const fileInput = await page.$('input[type="file"][accept*="image"]');
  log.action('🖼️ ', '이미지', !!fileInput, fileInput ? path.basename(imagePath) : '입력창 없음');
  if (!fileInput) return;
  await fileInput.uploadFile(imagePath);
};

// 게시 버튼 클릭 + 응답 인터셉트로 게시글 코드 추출
const submitPostAndGetCode = (page) =>
  new Promise((resolve) => {
    const onResponse = async (res) => {
      if (res.url().includes('/api/v1/media/configure_text')) {
        try {
          const json = await res.json();
          const code = json?.media?.code;
          if (code) {
            page.off('response', onResponse);
            resolve(code);
          }
        } catch (e) { }
      }
    };
    page.on('response', onResponse);

    // 게시 버튼 클릭 — findPostButtonInPage 본문을 전달
    page.evaluate((findPostButtonSrc) => {
      const findPostButton = new Function('return ' + findPostButtonSrc)();
      const btn = findPostButton();
      if (btn) btn.click();
    }, findPostButtonInPage.toString());

    // 10초 타임아웃 + 리스너 cleanup
    setTimeout(() => {
      page.off('response', onResponse);
      resolve(null);
    }, 10000);
  });

// 답글 게시 (OG 카드 인식을 위해 본문 입력 후 게시)
const submitReply = async (page, replyText) => {
  // 답글 버튼 클릭
  const replyClicked = await page.evaluate(() => {
    const el = document.querySelector('svg[aria-label="답글"]')?.closest('[role="button"]');
    if (!el) return false;
    el.click();
    return true;
  });
  if (!replyClicked) {
    log.action('💬', '답글', false, '버튼 없음');
    return;
  }
  await delay(1500);

  // 답글 입력
  const replyInput = await page.$('div[contenteditable="true"][data-lexical-editor="true"]');
  if (!replyInput) {
    log.action('💬', '답글', false, '입력창 없음');
    return;
  }

  await page.evaluate((text) => {
    const el = document.querySelector('div[contenteditable="true"][data-lexical-editor="true"]');
    el.focus();
    document.execCommand('insertText', false, text);
  }, replyText);

  // URL 포함 시 OG 카드 로딩 대기
  if (/https?:\/\//.test(replyText)) {
    await page.waitForSelector('a[rel="nofollow noreferrer"] img', { timeout: 10000 })
      .then(() => log.step('답글 OG 카드 감지'))
      .catch(() => log.step('답글 OG 카드 미감지'));
  }
  await delay(500);
  await randomDelay(3000, 5000);

  // 답글 게시 버튼 클릭 — findPostButtonInPage 본문 전달
  const replyPosted = await page.evaluate((findPostButtonSrc) => {
    const findPostButton = new Function('return ' + findPostButtonSrc)();
    const btn = findPostButton();
    if (!btn) return false;
    btn.click();
    return true;
  }, findPostButtonInPage.toString());

  if (replyPosted) await randomDelay(3000, 5000);
  log.action('💬', '답글', replyPosted);
};

// 포스팅 전체 흐름
const runPosting = async (page) => {
  if (writePost !== 1) return;

  log.section('게시글 작성');
  await openComposeModal(page);
  await setPostTopic(page, POST_TOPIC);
  await setPostBody(page, POST_BODY);
  if (uploadImage === 1) await attachPostImage(page, POST_IMAGE);
  await delay(3000);

  const postCode = await submitPostAndGetCode(page);

  if (!postCode) {
    log.warn('게시글 URL 감지 실패');
    return;
  }

  const postUrl = `https://www.threads.net/@${process.env.NICK_NAME}/post/${postCode}`;
  log.ok(`게시 완료: ${postUrl}`);
  await delay(1500);
  await page.goto(postUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await delay(2000);

  // POST_REPLY 비어있으면 답글 건너뜀
  if (!POST_REPLY.trim()) {
    log.info('POST_REPLY 미설정 — 답글 건너뜀');
    return;
  }

  await submitReply(page, POST_REPLY);
};

// 종료 모드 처리
const handleShutdown = async (browser) => {
  if (RUN_MODE === 1) {
    log.info('브라우저 수동 종료 대기 중...');
    await new Promise(resolve => browser.on('disconnected', resolve));
    return;
  }
  await browser.close();
};

// API 기반 AI 모드가 설정된 경우 필요한 키가 모두 있는지 시작 전에 검증한다.
const validateAIConfig = () => {
  const required = [];

  if (AI_MODE === 4 || SECOND_AI_MODE === 4) {
    required.push({
      mode: 4,
      key: 'GEMINI_API_KEY',
      label: 'Gemini API',
    });
  }

  if (AI_MODE === 5 || SECOND_AI_MODE === 5) {
    required.push({
      mode: 5,
      key: 'OPENAI_API_KEY',
      label: 'GPT API',
    });
  }

  const missing = required.filter(item => !process.env[item.key]);
  if (!missing.length) return;

  for (const item of missing) {
    log.err(`AI_MODE/SECOND_AI_MODE에 ${item.mode} (${item.label})가 포함되어 있으나 .env에 ${item.key}가 없습니다.`);
    log.info(`.env 파일에 ${item.key}=your_key_here 를 추가한 후 다시 실행하세요.`);
  }

  process.exit(1);
};

// 메인 함수 — 흐름 조합만 담당
const main = async () => {
  validateAIConfig();

  // 확장 프로그램 경로 설정
  const extensionsDir = path.join(__dirname, 'extensions');
  const extensions = fs.existsSync(extensionsDir)
    ? (await fsPromises.readdir(extensionsDir))
      .filter(file => fs.statSync(path.join(extensionsDir, file)).isDirectory())
      .map(dir => `--load-extension=${path.join(extensionsDir, dir)}`)
    : [];

  // 사용자 정보 가져오기 (id만 프로필 디렉토리에 사용)
  const { id } = getUserCredentials();

  // 브라우저 프로필 디렉토리 생성
  const profileDir = await createBrowserProfileDir(id);
  if (!profileDir) {
    log.err('브라우저 프로필 디렉토리 생성 실패 — 종료');
    process.exit(1);
  }
  await normalizeChromeProfileState(profileDir);

  let browser;
  try {
    browser = await initBrowser(profileDir, extensions);
    const pages = await browser.pages();
    const page = pages.length > 0 ? pages[0] : await browser.newPage();

    await setupPage(page);

    // 로그인 수행 (사용자가 직접 로그인할 때까지 대기)
    log.section('세션 확인');
    await waitForManualLogin(page);

    // 닉네임 추출 및 저장
    await ensureSession(page);

    // 상호작용 단계
    await runInteractions(page);

    // 포스팅 단계
    await runPosting(page);

    // RUN_MODE에 따른 실행 방식 제어
    await handleShutdown(browser);

  } catch (error) {
    log.err(`오류: ${error.message}`);
  } finally {
    if (profileDir) await normalizeChromeProfileState(profileDir);
    if (browser && RUN_MODE === 2) {
      await browser.close().catch(() => { });
      log.info('브라우저 종료');
      process.exit(0);
    }
  }
};

// 스크립트 실행
main().catch(error => {
  log.err(`메인 함수 오류: ${error.message}`);
  process.exit(1);
});
