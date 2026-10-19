(() => {
  'use strict';
  const form=document.getElementById('auth-form'), onboarding=document.body.dataset.onboarding==='true';
  let mode='login';
  document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>{
    mode=button.dataset.mode;
    document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b===button));
    document.getElementById('name-field').hidden=mode!=='register';
    form.elements.name.required=mode==='register';
    document.getElementById('auth-title').textContent=mode==='register'?'A fresh start.':'Welcome back.';
    document.getElementById('auth-description').textContent=mode==='register'?'Create your account, then register your facility.':'Sign in to pick up where you left off.';
    form.elements.password.autocomplete=mode==='register'?'new-password':'current-password';
    form.elements.password.minLength=mode==='register'?8:1;
    form.querySelector('button[type="submit"] span').textContent=mode==='register'?'Create account':'Sign in';
    document.getElementById('auth-error').hidden=document.getElementById('auth-success').hidden=true;
  }));
  document.getElementById('show-password')?.addEventListener('click',event=>{
    const field=form.elements.password, show=field.type==='password';field.type=show?'text':'password';event.target.textContent=show?'Hide':'Show';
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(!form.reportValidity())return;
    const error=document.getElementById('auth-error'), success=document.getElementById('auth-success'), button=form.querySelector('button[type="submit"]');
    error.hidden=success.hidden=true;button.disabled=true;
    try{
      const response=await fetch(onboarding?'/api/facility/register':`/api/auth/${mode}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify(Object.fromEntries(new FormData(form)))});
      const result=await response.json();if(!response.ok)throw new Error(result.error||'Please try again.');
      if(result.redirect){location.href=result.redirect;return;}
      success.textContent=result.message;success.hidden=false;
    }catch(err){error.textContent=err.message||'Unable to connect. Please try again.';error.hidden=false;}
    button.disabled=false;
  });
})();
