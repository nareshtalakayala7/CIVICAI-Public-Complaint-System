(() => {
  const title = document.getElementById('complaintTitle');
  const description = document.getElementById('complaintDescription');
  const counter = document.getElementById('charCount');
  const analyze = document.getElementById('analyzeComplaint');
  const result = document.getElementById('triageResult');
  if (description && counter) {
    const update = () => counter.textContent = `${description.value.length} / 5000`;
    description.addEventListener('input', update); update();
  }
  if (analyze && result) analyze.addEventListener('click', async () => {
    const combined = `${title?.value || ''} ${description?.value || ''}`.trim();
    if (combined.length < 10) { result.hidden = false; result.textContent = 'Add a title and a few details first so the triage preview has useful context.'; return; }
    analyze.disabled = true; analyze.querySelector('b').textContent = 'Reviewing issue details…';
    try {
      const response = await fetch('/api/triage', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:title?.value || '',description:description?.value || ''})});
      if (!response.ok) throw new Error('Triage unavailable');
      const item = await response.json();
      result.innerHTML = `<b>Suggested: ${escapeText(item.category)}</b><div class="triage-tags"><span><i class="bi bi-diagram-3"></i> ${escapeText(item.department)}</span><span><i class="bi bi-lightning"></i> ${escapeText(item.priority)} priority</span><span><i class="bi bi-bullseye"></i> ${Math.round(item.confidence*100)}% confidence</span></div><small style="display:block;margin-top:8px;color:#8499ae">${escapeText(item.method)} · City staff verify every report.</small>`;
      result.hidden = false;
    } catch (error) { result.hidden = false; result.textContent = 'Preview is temporarily unavailable. The server will still analyze your report when you submit it.'; }
    finally { analyze.disabled = false; analyze.querySelector('b').textContent = 'Refresh AI triage preview'; }
  });
  const fileInput = document.getElementById('complaintImages');
  const preview = document.getElementById('filePreview');
  if (fileInput && preview) fileInput.addEventListener('change', () => {
    const files = Array.from(fileInput.files || []).slice(0,3);
    preview.innerHTML = files.map(file => `<span><i class="bi bi-image"></i> ${escapeText(file.name)} · ${Math.max(1,Math.round(file.size/1024))} KB</span>`).join('');
    if ((fileInput.files || []).length > 3) preview.innerHTML += '<span>Only the first 3 images will be uploaded.</span>';
  });
  const locate = document.getElementById('locateButton');
  if (locate) locate.addEventListener('click', () => {
    const hint = document.getElementById('locationHint');
    if (!navigator.geolocation) { hint.textContent = 'Your browser does not provide location access.'; return; }
    locate.disabled = true; locate.innerHTML = '<i class="bi bi-hourglass-split"></i> Finding…';
    navigator.geolocation.getCurrentPosition(pos => {
      document.getElementById('latitude').value = pos.coords.latitude.toFixed(6);
      document.getElementById('longitude').value = pos.coords.longitude.toFixed(6);
      hint.textContent = `Location attached · ${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)}`;
      locate.innerHTML = '<i class="bi bi-check2-circle"></i> Location added'; locate.disabled = false;
    }, () => { hint.textContent = 'Location was not available. Add a nearby street or landmark instead.'; locate.innerHTML = '<i class="bi bi-crosshair2"></i> Try again'; locate.disabled = false; }, {timeout:9000,maximumAge:60000});
  });
  function escapeText(value) { const node = document.createElement('span'); node.textContent = value; return node.innerHTML; }
})();
