function d(i,t=300){let e;const o=(...c)=>{e!==void 0&&clearTimeout(e),e=setTimeout(()=>{e=void 0,i(...c)},t)};return o.cancel=()=>{e!==void 0&&(clearTimeout(e),e=void 0)},o}export{d};
