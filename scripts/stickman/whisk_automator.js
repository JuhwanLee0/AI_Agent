/**
 * Google Labs Whisk (https://labs.google/fx/ko/tools/whisk) Puppeteer 자동화 스크립트
 * 
 * - prompts.txt 파일의 영문 프롬프트를 한 줄씩 순차 주입하여 이미지를 자동 생성합니다.
 * - 생성된 고화질 이미지를 output/images/ 폴더에 순번대로(001.png, 002.png...) 자동 다운로드합니다.
 * - 최초 구글 로그인 세션을 browser_profile에 영구 저장하여 다음부터는 무인 자동 실행됩니다.
 */

const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');
const fsPromises = fs.promises;
const https = require('https');
const http = require('http');

// 컬러 로거
const log = {
  section: (title) => console.log(`\n\x1b[1m\x1b[34m┌ ── ${title} ──────────────────────\x1b[0m`),
  step: (msg) => console.log(`  \x1b[90m→\x1b[0m ${msg}`),
  ok: (msg) => console.log(`  \x1b[32m✓\x1b[0m ${msg}`),
  warn: (msg) => console.log(`  \x1b[33m⚠\x1b[0m ${msg}`),
  err: (msg) => console.error(`  \x1b[31m✗\x1b[0m \x1b[1m${msg}\x1b[0m`),
  action: (icon, label, detail = '') => console.log(`   ${icon} \x1b[97m${label.padEnd(10)}\x1b[0m ${detail ? `\x1b[90m${detail}\x1b[0m` : ''}`),
};

const delay = (ms) => new Promise(res => setTimeout(res, ms));

// 크롬 실행 파일 경로 탐색
const findChromePath = () => {
  const platform = process.platform;
  const macPaths = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
  ];
  const winPaths = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, 'Google', 'Chrome', 'Application', 'chrome.exe') : '',
  ].filter(Boolean);
  const linuxPaths = ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium'];

  const candidates = platform === 'darwin' ? macPaths : platform === 'win32' ? winPaths : linuxPaths;
  return candidates.find(p => fs.existsSync(p)) || undefined;
};

// URL로부터 이미지를 다운로드하여 로컬 파일로 저장
const downloadImage = (url, destPath) => {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(destPath);
    const client = url.startsWith('https') ? https : http;

    client.get(url, (response) => {
      if (response.statusCode !== 200) {
        reject(new Error(`이미지 다운로드 실패 (상태 코드: ${response.statusCode})`));
        return;
      }
      response.pipe(file);
      file.on('finish', () => {
        file.close(resolve);
      });
    }).on('error', (err) => {
      fs.unlink(destPath, () => {});
      reject(err);
    });
  });
};

const main = async () => {
  const args = process.argv.slice(2);
  let promptsFile = 'whisk_prompts.txt';
  let outDir = path.join(__dirname, '..', '..', 'output', 'images');

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--prompts' || args[i] === '-p') promptsFile = args[++i];
    if (args[i] === '--out' || args[i] === '-o') outDir = args[++i];
  }

  const resolvedPrompts = path.resolve(process.cwd(), promptsFile);
  if (!fs.existsSync(resolvedPrompts)) {
    log.err(`프롬프트 파일 '${resolvedPrompts}'을 찾을 수 없습니다.`);
    log.step(`먼저 python3 scripts/stickman/prompt_extractor.py 로 프롬프트를 추출하세요.`);
    process.exit(1);
  }

  const prompts = fs.readFileSync(resolvedPrompts, 'utf-8')
    .split('\n')
    .map(l => l.trim())
    .filter(l => l && !l.startsWith('#'));

  log.section('Google Whisk 이미지 자동화');
  log.step(`총 ${prompts.length}개의 프롬프트를 처리합니다.`);
  await fsPromises.mkdir(outDir, { recursive: true });

  const profileDir = path.join(__dirname, '..', '..', 'browser_profile', 'whisk_profile');
  await fsPromises.mkdir(profileDir, { recursive: true });

  const chromePath = findChromePath();
  const browser = await puppeteer.launch({
    headless: false, // Whisk UI 상호작용 및 세션 확인을 위해 화면 표시
    defaultViewport: { width: 1440, height: 900 },
    executablePath: chromePath,
    userDataDir: profileDir,
    args: [
      '--disable-blink-features=AutomationControlled',
      '--start-maximized',
      '--lang=ko-KR,ko',
    ]
  });

  const page = (await browser.pages())[0] || await browser.newPage();
  
  log.step('Google Labs Whisk 접속 중...');
  await page.goto('https://labs.google/fx/ko/tools/whisk', { waitUntil: 'networkidle2', timeout: 60000 });
  await delay(2000);

  // 로그인 및 시작 대기
  log.ok('Whisk 로드 완료. 만약 로그인이 필요하다면 브라우저에서 로그인해 주세요.');
  
  // 프롬프트 입력 및 순차 생성 루프
  for (let i = 0; i < prompts.length; i++) {
    const promptText = prompts[i];
    const seq = String(i + 1).padStart(3, '0');
    const targetFile = path.join(outDir, `${seq}.png`);

    log.action('🎨', `[${i + 1}/${prompts.length}]`, promptText.substring(0, 50) + '...');

    try {
      // 프롬프트 입력창 탐색 (textarea 또는 contenteditable)
      const inputSelector = 'textarea, input[type="text"], div[contenteditable="true"]';
      await page.waitForSelector(inputSelector, { timeout: 15000 });
      
      const inputEl = await page.$(inputSelector);
      if (inputEl) {
        // 기존 텍스트 지우고 입력
        await inputEl.click({ clickCount: 3 });
        await page.keyboard.press('Backspace');
        await page.keyboard.type(promptText, { delay: 20 });
        await delay(500);

        // 생성 버튼 클릭 (Enter 키 또는 제출 버튼)
        await page.keyboard.press('Enter');
        
        // 생성 대기 (새로운 이미지 로딩 대기: 최대 40초)
        log.step('이미지 렌더링 대기 중...');
        await delay(12000); // Whisk 기본 생성 주기

        // 생성된 최신 이미지 URL 추출 시도
        const imgUrl = await page.evaluate(() => {
          const imgs = Array.from(document.querySelectorAll('img[src*="http"], img[src^="blob:"]'));
          const validImgs = imgs.filter(img => img.naturalWidth > 300 || img.width > 300);
          return validImgs.length > 0 ? validImgs[validImgs.length - 1].src : null;
        });

        if (imgUrl && imgUrl.startsWith('http')) {
          await downloadImage(imgUrl, targetFile);
          log.ok(`이미지 저장 성공 ➔ ${path.basename(targetFile)}`);
        } else {
          // 스크린샷으로 대체 캡처 (안전 폴백)
          log.warn('직접 다운로드 실패 ➔ 화면 캡처 폴백 진행');
          await page.screenshot({ path: targetFile, clip: { x: 400, y: 150, width: 800, height: 600 } });
          log.ok(`캡처본 저장 ➔ ${path.basename(targetFile)}`);
        }
      }
    } catch (err) {
      log.err(`씬 ${i + 1} 생성 실패: ${err.message}`);
    }

    await delay(2000);
  }

  log.section('생성 완료');
  log.ok(`모든 이미지가 '${outDir}' 폴더에 저장되었습니다.`);
  log.step('브라우저를 종료하려면 창을 닫아주세요.');
};

main().catch(err => {
  log.err(`실행 오류: ${err.message}`);
  process.exit(1);
});
