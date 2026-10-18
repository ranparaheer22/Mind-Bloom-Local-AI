/* ============================================
   MIND BLOOM — Global JS
   ============================================ */

// ── THEME (dark/light mode) — applied immediately, before anything else, to minimize flash ──
(function applyStoredTheme() {
  try {
    const stored = localStorage.getItem('mb_theme');
    const isDark = stored === 'dark';
    document.documentElement.classList.toggle('dark-mode', isDark);
    window.addEventListener('DOMContentLoaded', () => {
      const icon = document.getElementById('theme-fab-icon');
      if (icon) icon.textContent = isDark ? '☀️' : '🌙';
    });
  } catch (e) { /* localStorage unavailable — default to light mode */ }
})();

function toggleTheme() {
  const isDark = document.documentElement.classList.toggle('dark-mode');
  try { localStorage.setItem('mb_theme', isDark ? 'dark' : 'light'); } catch (e) {}
  const icon = document.getElementById('theme-fab-icon');
  if (icon) icon.textContent = isDark ? '☀️' : '🌙';
}

// ── SESSION STORAGE HELPERS ──
const MB = {
  get: (key) => { try { return JSON.parse(sessionStorage.getItem('mb_' + key)); } catch { return null; } },
  set: (key, val) => sessionStorage.setItem('mb_' + key, JSON.stringify(val)),
  clear: () => { Object.keys(sessionStorage).filter(k => k.startsWith('mb_')).forEach(k => sessionStorage.removeItem(k)); }
};

// ── TRANSLATIONS ──
const TRANSLATIONS = {
  en: {
    next: "Next →",
    proceed: "Proceed →",
    help: "Help 💡",
    loading: "Mind Bloom",
    how_feeling: "How are you feeling right now?",
    select_lang: "Select Language",
    login_title: "Tell Us About You",
    name_label: "Your Name",
    age_label: "Your Age",
    gender_label: "Gender",
    birth_label: "Date of Birth",
    privacy_note: "🔒 Your info stays private and is only used to personalise your experience.",
    male: "Male", female: "Female", other: "Prefer not to say",
    name_placeholder: "e.g. Aanya, Rohan…",
    age_error: "Oops! Age must be between 5 and 123 🙈",
    required_error: "Hey hey hey! Fill all fields first 🙃",
    refresh_warn: "Arey! 😱 Are you sure you want to leave? Your progress will be lost!",
    lifestyle_title: "Answer These Basic Lifestyle Questions",
    gad_title: "Anxiety Score Test",
    phq_title: "Depression Score Test",
    result_title: "Your Mental Health Report",
    end_title: "Thank You!",
    download_pdf: "📥 Download Report as PDF",
    logout: "Logout 👋",
    check_anxiety: "Check Anxiety Score →",
    check_depression: "Check Depression Score →",
    check_result: "Check My Result →",
    q_sleep: "On average, how many hours do you sleep per night?",
    q_work: "How many hours per day do you spend working or studying?",
    q_activity: "How many days per week do you do physical activity?",
    q_screen: "How many hours per day do you spend on screens?",
    q_social: "How would you rate your social interaction?",
    q_caffeine: "How much caffeine do you consume daily?",
    q_alcohol: "How often do you consume alcohol?",
    q_family: "Do you have a family history of mental health condition?",
    q_therapy: "Have you ever received therapy or counseling?",
    gad_questions: [
      "Feeling nervous, anxious, or on edge?",
      "Not being able to stop or control worrying?",
      "Worrying too much about different things?",
      "Trouble relaxing?",
      "Being so restless that it's hard to sit still?",
      "Becoming easily annoyed or irritable?",
      "Feeling afraid, as if something awful might happen?"
    ],
    phq_questions: [
      "Little interest or pleasure in doing things?",
      "Feeling down, depressed, or hopeless?",
      "Trouble falling or staying asleep, or sleeping too much?",
      "Feeling tired or having little energy?",
      "Poor appetite or overeating?",
      "Feeling bad about yourself — or that you are a failure?",
      "Trouble concentrating on things, such as reading or watching TV?",
      "Moving or speaking so slowly that other people could have noticed? Or so fidgety or restless that you've been moving around a lot more than usual?",
      "Thoughts that you would be better off dead, or of hurting yourself?"
    ],
    options_freq: ["Not at all", "Several days", "More than half the days", "Nearly every day"],
  },
  hi: {
    next: "आगे →",
    proceed: "आगे बढ़ें →",
    help: "मदद 💡",
    loading: "माइंड ब्लूम",
    how_feeling: "अभी आप कैसा महसूस कर रहे हैं?",
    select_lang: "भाषा चुनें",
    login_title: "हमें अपने बारे में बताएं",
    name_label: "आपका नाम",
    age_label: "आपकी उम्र",
    gender_label: "लिंग",
    birth_label: "जन्म तिथि",
    privacy_note: "🔒 आपकी जानकारी पूरी तरह सुरक्षित है।",
    male: "पुरुष", female: "महिला", other: "बताना नहीं चाहते",
    name_placeholder: "जैसे आन्या, रोहन…",
    age_error: "अरे! उम्र 5 से 123 के बीच होनी चाहिए 🙈",
    required_error: "अरे यार! पहले सभी जानकारी भरें 🙃",
    refresh_warn: "अरे! 😱 क्या आप वाकई जाना चाहते हैं? आपकी प्रगति खो जाएगी!",
    lifestyle_title: "ये बुनियादी जीवनशैली प्रश्न उत्तर दें",
    gad_title: "चिंता स्कोर परीक्षण",
    phq_title: "अवसाद स्कोर परीक्षण",
    result_title: "आपकी मानसिक स्वास्थ्य रिपोर्ट",
    end_title: "धन्यवाद!",
    download_pdf: "📥 रिपोर्ट PDF में डाउनलोड करें",
    logout: "लॉगआउट 👋",
    check_anxiety: "चिंता स्कोर जांचें →",
    check_depression: "अवसाद स्कोर जांचें →",
    check_result: "मेरा परिणाम देखें →",
    q_sleep: "औसतन आप रात में कितने घंटे सोते हैं?",
    q_work: "आप प्रतिदिन काम या पढ़ाई में कितने घंटे बिताते हैं?",
    q_activity: "आप प्रति सप्ताह कितने दिन शारीरिक गतिविधि करते हैं?",
    q_screen: "आप प्रतिदिन स्क्रीन पर कितने घंटे बिताते हैं?",
    q_social: "आप अपनी सामाजिक बातचीत को कैसे आंकते हैं?",
    q_caffeine: "आप प्रतिदिन कितनी कैफीन लेते हैं?",
    q_alcohol: "आप कितनी बार शराब पीते हैं?",
    q_family: "क्या आपके परिवार में मानसिक स्वास्थ्य की समस्या का इतिहास है?",
    q_therapy: "क्या आपने कभी थेरेपी या काउंसलिंग ली है?",
    gad_questions: [
      "घबराहट, चिंता या बेचैनी महसूस होना?",
      "चिंता को रोकने या नियंत्रित करने में असमर्थ होना?",
      "विभिन्न चीजों के बारे में बहुत अधिक चिंता करना?",
      "आराम करने में कठिनाई?",
      "इतना बेचैन होना कि बैठना मुश्किल हो?",
      "आसानी से चिड़चिड़ा या नाराज हो जाना?",
      "कुछ बुरा होने का डर महसूस होना?"
    ],
    phq_questions: [
      "चीजें करने में कम रुचि या खुशी?",
      "उदास, निराश या बेहाल महसूस करना?",
      "सोने में परेशानी या बहुत ज्यादा सोना?",
      "थकान महसूस करना या कम ऊर्जा होना?",
      "कम भूख लगना या अधिक खाना?",
      "खुद के बारे में बुरा महसूस करना?",
      "एकाग्रता में परेशानी?",
      "इतना धीरे चलना या बोलना कि दूसरों ने नोटिस किया हो?",
      "खुद को नुकसान पहुंचाने के विचार?"
    ],
    options_freq: ["बिल्कुल नहीं", "कई दिन", "आधे से ज्यादा दिन", "लगभग हर दिन"],
  },
  gu: {
    next: "આગળ →",
    proceed: "આગળ વધો →",
    help: "મદદ 💡",
    loading: "માઇન્ડ બ્લૂમ",
    how_feeling: "તમે અત્યારે કેવું અનુભવ કરો છો?",
    select_lang: "ભાષા પસંદ કરો",
    login_title: "અમને તમારા વિશે જણાવો",
    name_label: "તમારું નામ",
    age_label: "તમારી ઉંમર",
    gender_label: "લિંગ",
    birth_label: "જન્મ તારીખ",
    privacy_note: "🔒 તમારી માહિતી સુરક્ષિત છે.",
    male: "પુરુષ", female: "સ્ત્રી", other: "કહેવું નથી",
    name_placeholder: "દા.ત. અાન્યા, રોહન…",
    age_error: "અરે! ઉંમર 5 થી 123 ની વચ્ચે હોવી જોઈએ 🙈",
    required_error: "અરે ભાઈ! પહેલા બધી માહિતી ભરો 🙃",
    refresh_warn: "અરે! 😱 શું તમે ખરેખર જવા માંગો છો? તમારી પ્રગ્રેસ ખોવાઈ જશે!",
    lifestyle_title: "આ મૂળભૂત જીવનશૈલી પ્રશ્નોના જવાબ આપો",
    gad_title: "ચિંતા સ્કોર ટેસ્ટ",
    phq_title: "ડિપ્રેશન સ્કોર ટેસ્ટ",
    result_title: "તમારો માનસિક સ્વાસ્થ્ય અહેવાલ",
    end_title: "આભાર!",
    download_pdf: "📥 PDF તરીકે રિપોર્ટ ડાઉનલોડ કરો",
    logout: "લૉગઆઉટ 👋",
    check_anxiety: "ચિંતા સ્કોર તપાસો →",
    check_depression: "ડિપ્રેશન સ્કોર તપાસો →",
    check_result: "મારું પરિણામ જુઓ →",
    q_sleep: "સરેરાશ, તમે રાત્રે કેટલા કલાક સૂઓ છો?",
    q_work: "તમે દરરોજ કામ અથવા અભ્યાસમાં કેટલા કલાક વિતાવો છો?",
    q_activity: "તમે અઠવાડિયામાં કેટલા દિવસ શારીરિક પ્રવૃત્તિ કરો છો?",
    q_screen: "તમે દરરોજ સ્ક્રીન પર કેટલા કલાક વિતાવો છો?",
    q_social: "તમે તમારી સામાજિક ક્રિયાપ્રતિક્રિયાને કેવી રીતે આંકો છો?",
    q_caffeine: "તમે દરરોજ કેટલી કેફીન લો છો?",
    q_alcohol: "તમે કેટલી વાર દારૂ પીઓ છો?",
    q_family: "શું તમારા પરિવારમાં માનસિક સ્વાસ્થ્ય સ્થિતિનો ઇતિહાસ છે?",
    q_therapy: "શું તમે ક્યારેય ઉપચાર અથવા કાઉન્સેલિંગ મેળવ્યું છે?",
    gad_questions: [
      "ગભરામણ, ચિંતા, અથવા ખળભળાટ અનુભવવો?",
      "ચિંતા અટકાવવા કે નિયંત્રણ કરવામાં અસમર્થ?",
      "વિવિધ બાબતો વિશે વધારે ચિંતા?",
      "આરામ કરવામાં તકલીફ?",
      "એટલા બેચેન કે બેસવું અઘરું?",
      "સહેલાઈથી ચીડ ચઢવી?",
      "કઈ ખરાબ ઘટના બનશે એ ડર?"
    ],
    phq_questions: [
      "કામ કરવામાં ઓછો રસ?",
      "ઉદાસ, નિરાશ, અથવા ખાલી અનુભવ?",
      "ઊંઘ ન આવવી અથવા ખૂબ ઊંઘ?",
      "થાક અથવા ઓછી ઊર્જા?",
      "ઓછો ભૂખ અથવા વધારે ખાવું?",
      "પોતા વિશે ખરાબ અનુભવ?",
      "ધ્યાન કેન્દ્રિત કરવામાં તકલીફ?",
      "ખૂબ ધીમું ચાલવું/બોલવું?",
      "ખુદને નુકસાન કરવાના વિચારો?"
    ],
    options_freq: ["બિલ્કુલ નહીં", "ઘણા દિવસ", "અડધા કરતાં વધુ દિવસ", "લગભગ દરરોજ"],
  }
};

function t(key) {
  const lang = MB.get('lang') || 'en';
  return (TRANSLATIONS[lang] && TRANSLATIONS[lang][key]) || TRANSLATIONS['en'][key] || key;
}

// ── LOADER ──
function hideLoader() {
  const loader = document.getElementById('page-loader');
  if (loader) {
    setTimeout(() => loader.classList.add('hide'), 400);
  }
}

function navigateTo(url, delay = 300) {
  document.body.style.opacity = '0';
  document.body.style.transition = 'opacity 0.3s ease';
  setTimeout(() => { window.location.href = url; }, delay);
}

// ── REFRESH WARNING ──
function setupRefreshWarning() {
  window.addEventListener('beforeunload', (e) => {
    const msg = t('refresh_warn');
    e.preventDefault();
    e.returnValue = msg;
    return msg;
  });
}

// ── TOAST ──
function showToast(title, msg, type = 'info') {
  let toast = document.getElementById('global-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'global-toast';
    toast.className = 'toast';
    document.body.appendChild(toast);
  }
  const icons = { info: '💬', warn: '⚠️', error: '🙈', success: '✅' };
  toast.innerHTML = `
    <div class="toast-icon">${icons[type]}</div>
    <div>
      <div class="toast-title">${title}</div>
      <div class="toast-msg">${msg}</div>
    </div>`;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 4000);
}

// ── PAGE LOAD ──
window.addEventListener('DOMContentLoaded', () => {
  hideLoader();
  applyLanguage();
});

// ── APPLY TRANSLATIONS ──
function applyLanguage() {
  const lang = MB.get('lang') || 'en';
  document.querySelectorAll('[data-t]').forEach(el => {
    const key = el.getAttribute('data-t');
    const val = t(key);
    if (val) el.textContent = val;
  });
  document.querySelectorAll('[data-t-placeholder]').forEach(el => {
    const key = el.getAttribute('data-t-placeholder');
    el.placeholder = t(key);
  });
}

// ── CONFETTI (lightweight) ──
function launchConfetti(container) {
  const colors = ['#5a8a5a','#a8c8a8','#c9a96e','#d1e2d1','#7aaa7a'];
  for (let i = 0; i < 60; i++) {
    const p = document.createElement('div');
    p.style.cssText = `
      position:absolute;
      width:${Math.random()*8+4}px;
      height:${Math.random()*8+4}px;
      background:${colors[Math.floor(Math.random()*colors.length)]};
      border-radius:${Math.random()>0.5?'50%':'2px'};
      left:${Math.random()*100}%;
      top:-10px;
      opacity:1;
      animation: confettiFall ${1.5+Math.random()*1.5}s ease-in ${Math.random()*0.5}s forwards;
    `;
    container.appendChild(p);
  }
  if (!document.getElementById('confetti-style')) {
    const s = document.createElement('style');
    s.id = 'confetti-style';
    s.textContent = `@keyframes confettiFall {
      to { transform: translateY(420px) rotate(${Math.random()*360}deg); opacity:0; }
    }`;
    document.head.appendChild(s);
  }
}

// ── SCORE RING DRAW ──
function drawScoreRing(svgId, score, max, color) {
  const svg = document.getElementById(svgId);
  if (!svg) return;
  const r = 54, cx = 60, cy = 60;
  const circ = 2 * Math.PI * r;
  const pct = Math.min(score / max, 1);
  const dash = pct * circ;
  svg.innerHTML = `
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#e8f0e8" stroke-width="10"/>
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="10"
      stroke-dasharray="${dash} ${circ - dash}"
      stroke-linecap="round"
      style="transition:stroke-dasharray 1s ease"/>
  `;
}

// ── RADAR CHART (canvas-free SVG) ──
function drawRadarChart(containerId, labels, values, maxVal) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const n = labels.length;
  const cx = 180, cy = 180, r = 140;
  const angleStep = (2 * Math.PI) / n;
  const getPoint = (i, radius) => {
    const angle = i * angleStep - Math.PI / 2;
    return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
  };
  let gridPaths = '';
  [0.25, 0.5, 0.75, 1].forEach(frac => {
    const pts = Array.from({length:n}, (_,i) => getPoint(i, r*frac));
    gridPaths += `<polygon points="${pts.map(p=>p.join(',')).join(' ')}"
      fill="none" stroke="#d1e2d1" stroke-width="1"/>`;
  });
  let axisLines = '';
  for (let i = 0; i < n; i++) {
    const [x, y] = getPoint(i, r);
    axisLines += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}"
      stroke="#d1e2d1" stroke-width="1"/>`;
  }
  const dataPoints = values.map((v, i) => getPoint(i, r * Math.min(v / maxVal, 1)));
  const dataPath = dataPoints.map((p,i) => (i===0?'M':'L')+p.join(',')).join(' ') + 'Z';
  let labelEls = '';
  for (let i = 0; i < n; i++) {
    const [x, y] = getPoint(i, r + 24);
    labelEls += `<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle"
      font-size="11" fill="#4a5e4a" font-family="DM Sans,sans-serif">${labels[i]}</text>`;
  }
  container.innerHTML = `
    <svg viewBox="0 0 360 360" width="100%" style="max-width:360px;display:block;margin:0 auto">
      ${gridPaths}${axisLines}
      <path d="${dataPath}" fill="rgba(90,138,90,0.2)" stroke="#5a8a5a" stroke-width="2.5"
        stroke-linejoin="round"/>
      ${dataPoints.map(p=>`<circle cx="${p[0]}" cy="${p[1]}" r="5" fill="#5a8a5a"/>`).join('')}
      ${labelEls}
    </svg>`;
}

// ── BAR CHART SVG ──
function drawBarChart(containerId, labels, values, colors) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const w = 340, barH = 32, gap = 14, padL = 120, padR = 20, padT = 10;
  const maxV = Math.max(...values, 1);
  const svgH = padT + labels.length * (barH + gap);
  let bars = '';
  labels.forEach((lbl, i) => {
    const y = padT + i * (barH + gap);
    const bw = ((values[i] / maxV) * (w - padL - padR));
    bars += `
      <text x="${padL - 8}" y="${y + barH/2 + 1}" text-anchor="end"
        dominant-baseline="middle" font-size="12" fill="#4a5e4a" font-family="DM Sans">${lbl}</text>
      <rect x="${padL}" y="${y}" width="${bw}" height="${barH}" rx="6"
        fill="${colors[i % colors.length]}" opacity="0.85"/>
      <text x="${padL + bw + 6}" y="${y + barH/2 + 1}"
        dominant-baseline="middle" font-size="12" fill="#2c3e2c" font-family="DM Sans"
        font-weight="500">${values[i]}%</text>
    `;
  });
  container.innerHTML = `
    <svg viewBox="0 0 ${w} ${svgH}" width="100%" style="display:block;margin:0 auto">
      ${bars}
    </svg>`;
}
