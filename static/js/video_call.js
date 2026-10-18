/* Mind Bloom Animated VideoBot — English-only, conversational Gemini chat, gender-matched browser voices. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var CFG = window.MB_VIDEO || { crisis: [] };
  var active = false, gender = 'female', seconds = 0, timer = null;
  var chatSessionId = null, sending = false, recognition = null, cameraStream = null, micOn = false, lastReply = '';
  var NAMES = { female: 'Racheal', male: 'Ryan' };
  var GREETINGS = {
    female: 'Hi, I’m Racheal. What would you like to talk about today?',
    male: 'Hey, I’m Ryan. What’s been on your mind today?'
  };
  function status(t) { $('call-status').textContent = t; }
  function fmt(n) { return String(Math.floor(n / 60)).padStart(2,'0') + ':' + String(n % 60).padStart(2,'0'); }
  function setSpeaking(on) {
    var svg = $('avatar-box').querySelector('.av-svg');
    if (svg) svg.classList.toggle('speaking', !!on);
  }
  function updateHub() {
    document.querySelectorAll('.vp-card').forEach(function (c) {
      c.classList.toggle('active', c.dataset.gender === gender);
      c.setAttribute('aria-pressed', c.dataset.gender === gender ? 'true' : 'false');
    });
    $('start-call-btn').textContent = '▶ Start animated chat with ' + NAMES[gender];
    $('voice-hint').textContent = 'English conversation · natural replies · local animated character';
    $('voice-hint').style.display = 'block';
    $('type-input').placeholder = 'Type your message…';
  }
  try { gender = localStorage.getItem('mb_video_gender') === 'male' ? 'male' : 'female'; } catch (e) {}
  document.querySelectorAll('.vp-card').forEach(function (card) {
    card.addEventListener('click', function () {
      if (active) return;
      gender = card.dataset.gender === 'male' ? 'male' : 'female';
      try { localStorage.setItem('mb_video_gender', gender); } catch (e) {}
      updateAvatar(); updateHub();
    });
    card.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); }
    });
  });
  function updateAvatar() {
    var box = $('avatar-box');
    if (!box) return;
    var macroHtml = document.querySelector('.vp-card[data-gender="' + gender + '"] .vp-avatar');
    if (macroHtml) box.innerHTML = macroHtml.innerHTML;
    $('call-name').textContent = NAMES[gender];
  }

  // Browser speech synthesis does not infer a speaker's gender from pitch alone.
  // Select an explicitly female/male-named installed voice whenever one is available.
  function voiceScore(voice, wantedGender) {
    var name = (voice.name || '').toLowerCase();
    var lang = (voice.lang || '').toLowerCase();
    var femaleNames = ['zira','aria','jenny','samantha','susan','hazel','heera','veena','sonia','libby','karen','victoria','katherine','eva','female','google us english','google uk english female'];
    var maleNames = ['david','mark','guy','ryan','george','prabhat','male','google uk english male'];
    var positives = wantedGender === 'female' ? femaleNames : maleNames;
    var negatives = wantedGender === 'female' ? maleNames : femaleNames;
    var score = 0;
    positives.forEach(function (term) { if (name.indexOf(term) !== -1) score += term === 'female' || term === 'male' ? 8 : 12; });
    negatives.forEach(function (term) { if (name.indexOf(term) !== -1) score -= 18; });
    if (lang === 'en-in') score += 5;
    else if (lang.indexOf('en-') === 0) score += 3;
    else if (lang === 'en') score += 2;
    if (voice.default) score += 1;
    return score;
  }
  function chooseVoice() {
    if (!('speechSynthesis' in window)) return null;
    var voices = window.speechSynthesis.getVoices() || [];
    if (!voices.length) return null;
    var english = voices.filter(function (v) { return (v.lang || '').toLowerCase().indexOf('en') === 0; });
    var candidates = english.length ? english : voices;
    candidates.sort(function (a,b) { return voiceScore(b, gender) - voiceScore(a, gender); });
    // Use the best available English voice, even when its platform name is unfamiliar.
    // Returning null here can make speech silently fail on Windows/Android voices.
    return candidates[0] || voices[0] || null;
  }
  function speak(text, voiceRetry) {
    if (!text || !('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') {
      status('Voice playback is unavailable in this browser. Try Chrome or enable text-to-speech in Android settings.');
      return;
    }
    // Some browsers populate voices only after the page has been used once.
    var voices = window.speechSynthesis.getVoices() || [];
    if (!voices.length && (voiceRetry || 0) < 8) {
      window.setTimeout(function () { speak(text, (voiceRetry || 0) + 1); }, 350);
      return;
    }
    window.speechSynthesis.cancel();
    window.speechSynthesis.resume();
    var utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-IN';
    var selectedVoice = chooseVoice();
    if (selectedVoice) {
      utterance.voice = selectedVoice;
      utterance.lang = selectedVoice.lang || 'en-IN';
    }
    utterance.rate = 0.96;
    // Pitch is only a fallback; the selected voice is what primarily controls gender presentation.
    utterance.pitch = gender === 'female' ? 1.16 : 0.91;
    utterance.onstart = function () { setSpeaking(true); status(NAMES[gender] + ' is speaking…'); };
    utterance.onend = function () { setSpeaking(false); if (active) status('Listening or type a message'); };
    utterance.onerror = function (event) {
      setSpeaking(false);
      if (active) status('Voice playback failed (' + (event.error || 'unknown error') + '). Check device volume and text-to-speech settings.');
    };
    window.speechSynthesis.speak(utterance);
    // Resume again after speak for Chromium implementations that retain a paused queue.
    window.setTimeout(function () { if (window.speechSynthesis.paused) window.speechSynthesis.resume(); }, 100);
  }
  function replayLastReply() {
    if (!lastReply) { status('There is no reply to replay yet.'); return; }
    speak(lastReply);
  }
  var replayButton = $('btn-speak-reply');
  if (replayButton) replayButton.addEventListener('click', replayLastReply);
  if ('speechSynthesis' in window) {
    window.speechSynthesis.onvoiceschanged = function () { /* refresh voice list before the next reply */ };
  }
  async function startCall() {
    if (active) return;
    // Warm up browser speech synthesis from the Start button gesture.
    try { if ('speechSynthesis' in window) { window.speechSynthesis.cancel(); window.speechSynthesis.resume(); window.speechSynthesis.getVoices(); } } catch (e) {}
    active = true; seconds = 0; sending = false;
    $('ended-card').style.display = 'none'; $('call-screen').classList.add('open');
    $('cap-you').textContent = ''; $('cap-doc').textContent = 'Connecting to Mind Bloom…';
    updateAvatar(); $('call-name').textContent = NAMES[gender]; status('Connecting to Mind Bloom…');
    $('call-timer').textContent = '00:00';
    timer = setInterval(function () { seconds++; $('call-timer').textContent = fmt(seconds); }, 1000);
    try {
      var res = await fetch('/api/chat/new', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({bot_type:'doctor', doctor_gender:gender})
      });
      var data = await res.json();
      if (!res.ok || !data.success || !data.session_id) throw new Error(data.error || 'Could not start a chat session.');
      chatSessionId = data.session_id;
      var greeting = GREETINGS[gender];
      $('cap-doc').textContent = greeting; lastReply = greeting; if ($('btn-speak-reply')) $('btn-speak-reply').style.display = 'inline-block'; status('Ready · talk or type naturally'); speak(greeting);
    } catch (e) {
      status('Could not connect'); $('cap-doc').textContent = e.message || 'Could not connect to Mind Bloom. Please try again.';
      active = false; clearInterval(timer); timer = null;
    }
  }
  async function sendMessage(raw) {
    var message = (raw || '').trim();
    if (!message || sending || !chatSessionId) return;
    sending = true; $('type-send').disabled = true; $('type-input').disabled = true;
    $('cap-you').textContent = 'You: ' + message; $('cap-doc').textContent = '';
    status('Thinking about what you said…');
    if (recognition && micOn) { try { recognition.stop(); } catch(e) {} }
    try {
      var res = await fetch('/api/chat/' + chatSessionId + '/message', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:message})
      });
      if (!res.ok || !res.body) {
        var err = {}; try { err = await res.json(); } catch(e) {}
        throw new Error(err.error || 'The message could not be sent. Please try again.');
      }
      var reader = res.body.getReader(), decoder = new TextDecoder(), buffer = '', answer = '';
      while (true) {
        var part = await reader.read(); if (part.done) break;
        buffer += decoder.decode(part.value, {stream:true});
        var lines = buffer.split('\n'); buffer = lines.pop() || '';
        lines.forEach(function (line) {
          if (!line.trim()) return;
          try {
            var event = JSON.parse(line);
            if (event.type === 'chunk' && event.text) { answer += event.text; $('cap-doc').textContent = answer; }
            if (event.type === 'crisis') { $('cap-doc').textContent = 'Your safety matters. Please use the Help button for urgent support resources.'; }
          } catch(e) {}
        });
      }
      if (buffer.trim()) {
        try { var ev = JSON.parse(buffer); if (ev.type === 'chunk' && ev.text) answer += ev.text; } catch(e) {}
      }
      if (!answer.trim()) answer = 'I want to make sure I understand you. Could you say a little more about the part that matters most?';
      $('cap-doc').textContent = answer; lastReply = answer; if ($('btn-speak-reply')) $('btn-speak-reply').style.display = 'inline-block'; speak(answer);
    } catch (e) {
      $('cap-doc').textContent = e.message || 'Something went wrong. Please try again.'; status('Message failed');
    } finally {
      sending = false; $('type-send').disabled = false; $('type-input').disabled = false;
      $('type-input').value = ''; $('type-input').focus();
    }
  }
  function toggleKeyboard() {
    var bar = $('type-bar'); bar.classList.toggle('open');
    if (bar.classList.contains('open')) $('type-input').focus();
  }
  function toggleMic() {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { status('Speech input is not supported in this browser. Please type instead.'); $('type-bar').classList.add('open'); $('type-input').focus(); return; }
    if (micOn && recognition) { try { recognition.stop(); } catch(e) {} micOn = false; $('btn-mic').classList.remove('mic-active'); status('Microphone off'); return; }
    recognition = new SR(); recognition.lang = 'en-IN'; recognition.interimResults = true; recognition.continuous = false;
    recognition.onstart = function () { micOn = true; $('btn-mic').classList.add('mic-active'); status('Listening… speak now'); };
    recognition.onresult = function (event) {
      var text = ''; for (var i=event.resultIndex;i<event.results.length;i++) text += event.results[i][0].transcript;
      $('type-input').value = text;
      if (event.results[event.results.length-1].isFinal) { micOn = false; $('btn-mic').classList.remove('mic-active'); sendMessage(text); }
    };
    recognition.onerror = function () { micOn = false; $('btn-mic').classList.remove('mic-active'); status('Speech input stopped. You can type instead.'); };
    recognition.onend = function () { micOn = false; $('btn-mic').classList.remove('mic-active'); };
    try { recognition.start(); } catch(e) { status('Could not start speech input. Please type instead.'); }
  }
  async function toggleCamera() {
    if (cameraStream) {
      cameraStream.getTracks().forEach(function(t){t.stop();}); cameraStream = null;
      $('self-video').srcObject = null; $('self-view').style.display = 'none'; $('btn-cam').classList.add('off'); status('Camera preview off'); return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { status('Camera preview is not supported here.'); return; }
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({video:true,audio:false});
      $('self-video').srcObject = cameraStream; $('self-view').style.display = 'block'; $('btn-cam').classList.remove('off');
      status('Camera preview is local only');
    } catch(e) { status('Camera permission was not granted. The animated chat still works.'); }
  }
  function endCall() {
    active = false; clearInterval(timer); timer = null;
    if (recognition) { try { recognition.stop(); } catch(e) {} recognition = null; }
    micOn = false; $('btn-mic').classList.remove('mic-active');
    if ('speechSynthesis' in window) window.speechSynthesis.cancel(); setSpeaking(false);
    if (cameraStream) { cameraStream.getTracks().forEach(function(t){t.stop();}); cameraStream = null; }
    $('self-video').srcObject = null; $('self-view').style.display = 'none'; $('btn-cam').classList.add('off');
    $('type-bar').classList.remove('open'); $('call-screen').classList.remove('open');
    $('ended-time').textContent = fmt(seconds); $('ended-card').style.display = 'block';
    status('Session ended'); chatSessionId = null;
  }
  function openHelp(show) {
    var panel = $('help-panel'); panel.classList.toggle('open', show !== false);
    if (show === false) return;
    var resources = CFG.crisis || [];
    $('help-list').innerHTML = resources.map(function () {
      return '<div class="help-row"><div class="hr-name"></div><div class="hr-num"></div><div class="hr-note"></div></div>';
    }).join('') || '<div class="help-row">If you are in immediate danger in India, call 112.</div>';
    var rows = $('help-list').querySelectorAll('.help-row');
    resources.forEach(function(r,i){ if(!rows[i]) return; rows[i].querySelector('.hr-name').textContent=r.name||r.label||'Support'; rows[i].querySelector('.hr-num').textContent=r.phone||r.number||''; rows[i].querySelector('.hr-note').textContent=r.note||r.description||''; });
  }
  $('start-call-btn').addEventListener('click', startCall);
  $('btn-keyboard').addEventListener('click', toggleKeyboard);
  $('type-send').addEventListener('click', function(){ sendMessage($('type-input').value); });
  $('type-input').addEventListener('keydown', function(e){ if(e.key==='Enter'){e.preventDefault();sendMessage($('type-input').value);} if(e.key==='Escape') $('type-bar').classList.remove('open'); });
  $('btn-mic').addEventListener('click', toggleMic); $('btn-cam').addEventListener('click', toggleCamera);
  $('btn-end').addEventListener('click', endCall); $('btn-help').addEventListener('click', function(){openHelp(true);}); $('help-close').addEventListener('click', function(){openHelp(false);});
  $('stage').addEventListener('click', function(){ if ('speechSynthesis' in window) window.speechSynthesis.cancel(); setSpeaking(false); if(active) status('Ready · talk or type naturally'); });
  window.addEventListener('pagehide', function(){ if(cameraStream) cameraStream.getTracks().forEach(function(t){t.stop();}); if('speechSynthesis' in window) window.speechSynthesis.cancel(); });
  updateAvatar(); updateHub();
})();
