(() => {
  'use strict';
  const form=document.getElementById('auth-form'), onboarding=document.body.dataset.onboarding==='true';
  const csrf=document.querySelector('meta[name="csrf-token"]').content;
  let mode='login';
  const messages={login:['Welcome back.','Sign in to pick up where you left off.','Sign in'],register:['A fresh start.','Create your account, then register your facility.','Create account'],recover:['Reset your password.','We’ll send you a link. Open it in this browser to choose a new password.','Send reset link'],resend:['Check your inbox.','Request a new verification link for your account.','Resend verification']};
  function setMode(value){
    mode=value;
    const password=mode==='login'||mode==='register', [title,description,label]=messages[mode];
    document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));
    document.getElementById('name-field').hidden=mode!=='register';
    form.elements.name.required=mode==='register';
    document.getElementById('password-field').hidden=!password;
    form.elements.password.required=password;
    form.elements.password.value='';
    form.elements.password.autocomplete=mode==='register'?'new-password':'current-password';
    form.elements.password.minLength=mode==='register'?8:1;
    document.getElementById('auth-title').textContent=title;
    document.getElementById('auth-description').textContent=description;
    form.querySelector('button[type="submit"] span').textContent=label;
    document.getElementById('recovery-link').hidden=mode!=='login';
    document.getElementById('resend-link').hidden=mode!=='login';
    document.getElementById('back-to-login').hidden=password;
    document.getElementById('auth-error').hidden=document.getElementById('auth-success').hidden=true;
  }
  document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>setMode(button.dataset.mode)));
  document.getElementById('recovery-link')?.addEventListener('click',()=>setMode('recover'));
  document.getElementById('resend-link')?.addEventListener('click',()=>setMode('resend'));
  document.getElementById('back-to-login')?.addEventListener('click',()=>setMode('login'));
  document.getElementById('show-password')?.addEventListener('click',event=>{
    const field=form.elements.password, show=field.type==='password';field.type=show?'text':'password';event.target.textContent=show?'Hide':'Show';
  });
  document.getElementById('onboarding-logout')?.addEventListener('click',async()=>{
    const response=await fetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:'{}'});
    if(response.ok)location.assign('/login');
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(!form.reportValidity())return;
    const error=document.getElementById('auth-error'), success=document.getElementById('auth-success'), button=form.querySelector('button[type="submit"]');
    error.hidden=success.hidden=true;button.disabled=true;
    try{
      const response=await fetch(onboarding?'/api/facility/register':`/api/auth/${mode}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(Object.fromEntries(new FormData(form)))});
      const result=await response.json();if(!response.ok)throw new Error(result.error||'Please try again.');
      if(result.redirect){location.href=result.redirect;return;}
      success.textContent=result.message;success.hidden=false;
      if(form.elements.password)form.elements.password.value='';
    }catch(err){error.textContent=err.message||'Unable to connect. Please try again.';error.hidden=false;}
    button.disabled=false;
  });
})();
