<script>
(function(){
  var edges=$edges;
  var svg=document.getElementById('graph'),panel=document.getElementById('panel'),body=document.getElementById('panel-body');
  var nodes={},sel=null;
  svg.querySelectorAll('.node').forEach(function(n){nodes[n.getAttribute('data-id')]=n;});
  var wires=Array.prototype.slice.call(svg.querySelectorAll('.edge'));
  function light(id){
    var near={};near[id]=1;
    edges.forEach(function(e){if(e[0]===id)near[e[1]]=1;if(e[1]===id)near[e[0]]=1;});
    Object.keys(nodes).forEach(function(k){nodes[k].classList.toggle('dim',!near[k]);nodes[k].classList.toggle('on',k===id);});
    wires.forEach(function(w){var hot=w.getAttribute('data-from')===id||w.getAttribute('data-to')===id;w.classList.toggle('hot',hot);w.classList.toggle('dim',!hot);});
  }
  function clear(){
    if(sel){light(sel);return;}
    Object.keys(nodes).forEach(function(k){nodes[k].classList.remove('dim','on');});
    wires.forEach(function(w){w.classList.remove('hot','dim');});
  }
  function open(id){
    var t=document.getElementById('tpl-'+id);if(!t)return;
    sel=id;body.innerHTML='';body.appendChild(t.content.cloneNode(true));panel.hidden=false;light(id);
  }
  function close(){
    var was=sel;sel=null;panel.hidden=true;clear();if(was&&nodes[was])nodes[was].focus();
  }
  Object.keys(nodes).forEach(function(id){
    var n=nodes[id];
    n.addEventListener('mouseenter',function(){light(id);});
    n.addEventListener('mouseleave',clear);
    n.addEventListener('focus',function(){light(id);});
    n.addEventListener('blur',clear);
    n.addEventListener('click',function(){open(id);});
    n.addEventListener('keydown',function(ev){if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();open(id);}});
  });
  panel.querySelector('.close').addEventListener('click',close);
  document.addEventListener('keydown',function(ev){if(ev.key==='Escape'&&!panel.hidden)close();});
  svg.addEventListener('click',function(ev){if(ev.target===svg)close();});
})();
</script>