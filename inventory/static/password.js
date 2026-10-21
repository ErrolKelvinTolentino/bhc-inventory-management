(() => {
  'use strict';
  const form=document.getElementById('password-form');
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(!form.reportValidity())return;
    const button=form.querySelector('button[type="submit"]'),error=document.getElementById('password-error');
    button.disabled=true;error.hidden=true;
    try{
      const response=await fetch('/api/auth/password',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify(Object.fromEntries(new FormData(form)))});
      const result=await response.json();if(!response.ok)throw new Error(result.error||'Your password could not be changed.');
      location.assign(result.redirect);
    }catch(err){error.textContent=err.message;error.hidden=false;button.disabled=false;}
  });
})();
