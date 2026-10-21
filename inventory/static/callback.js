(() => {
  'use strict';
  const params=new URLSearchParams(location.hash.slice(1));
  history.replaceState(null,'',location.pathname);
  async function finish(){
    try{
      if(params.get('error'))throw new Error(params.get('error_description')||'This link is no longer valid.');
      if(!params.get('access_token')||!params.get('refresh_token'))throw new Error('This link is incomplete or already used. Request a new one.');
      const response=await fetch('/api/auth/callback',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({nonce:document.body.dataset.flow,access_token:params.get('access_token'),refresh_token:params.get('refresh_token')})});
      params.delete('access_token');params.delete('refresh_token');
      const result=await response.json();if(!response.ok)throw new Error(result.error||'The link could not be verified.');
      location.replace(result.redirect);
    }catch(error){document.getElementById('callback-title').textContent='Let’s try a new link.';document.getElementById('callback-message').textContent=error.message;document.getElementById('callback-return').hidden=false;}
  }
  finish();
})();
