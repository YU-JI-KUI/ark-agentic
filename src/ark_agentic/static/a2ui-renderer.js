(function () {
  'use strict';

  // ---- Constants ----
  var BORDER_RADIUS_MAP = { small: '4px', middle: '8px', big: '12px' };

  var TEXT_SIZE_MAP = {
    xsmall: '10px', small: '12px', normal: '14px',
    large: '16px', xlarge: '20px', xxlarge: '24px'
  };

  var USAGE_HINT_STYLES = {
    error:   { color: '#FF0000' },
    warning: { color: '#FF6600' },
    tips:    { color: '#A4A4A4' },
    info:    { color: '#333333' },
    title:   { color: '#222222', fontWeight: 'bold', fontSize: '16px' },
    link:    { color: '#0066CC', textDecoration: 'underline', cursor: 'pointer' }
  };

  var ICON_SIZE_MAP = {
    xsmall: '32px', small: '40px', middle: '48px',
    large: '56px', xlarge: '72px', xxlarge: '88px'
  };

  var BUTTON_TYPE_STYLES = {
    primary:   { background: '#f0762b', color: '#fff', border: 'none' },
    secondary: { background: 'transparent', color: '#f0762b', border: '1.5px solid #f0762b' },
    soft:      { background: '#fff0e6', color: '#f0762b', border: 'none' },
    normal:    { background: 'transparent', color: '#666', border: '1.5px solid #ccc' },
    info:      { background: 'transparent', color: '#f0762b', border: 'none', textDecoration: 'underline' }
  };

  var TAG_SIZE_MAP = {
    small:  { padding: '1px 6px', fontSize: '10px' },
    middle: { padding: '2px 8px', fontSize: '12px' },
    large:  { padding: '4px 12px', fontSize: '14px' }
  };

  // ---- Surface Registry ----
  var surfaces = new Map();

  // ---- Path Resolution ----
  function resolvePath(obj, path) {
    if (obj == null || !path) return undefined;
    var parts = path.split('.');
    var current = obj;
    for (var i = 0; i < parts.length; i++) {
      if (current == null) return undefined;
      current = current[parts[i]];
    }
    return current;
  }

  function resolveValue(binding, scopeData, globalData, depth) {
    if (!binding || (depth || 0) > 3) return '';
    if (binding.path !== undefined) {
      var v;
      if (scopeData != null) {
        v = resolvePath(scopeData, binding.path);
        if (v !== undefined) {
          if (v && typeof v === 'object' && !Array.isArray(v) &&
              (v.path !== undefined || v.literalString !== undefined)) {
            return resolveValue(v, null, globalData, (depth || 0) + 1);
          }
          return formatResolved(v);
        }
      }
      v = resolvePath(globalData, binding.path);
      if (v !== undefined) {
        if (v && typeof v === 'object' && !Array.isArray(v) &&
            (v.path !== undefined || v.literalString !== undefined)) {
          return resolveValue(v, null, globalData, (depth || 0) + 1);
        }
        return formatResolved(v);
      }
      if (binding.literalString !== undefined) {
        return formatResolved(binding.literalString);
      }
      return '';
    }
    if (binding.literalString !== undefined) {
      return formatResolved(binding.literalString);
    }
    return '';
  }

  function formatResolved(v) {
    if (v === null || v === undefined) return '';
    if (typeof v === 'object') return JSON.stringify(v);
    return String(v);
  }

  function resolveBoolean(binding, globalData) {
    if (!binding) return false;
    if (binding.path !== undefined) {
      var v = resolvePath(globalData, binding.path);
      if (v !== undefined) return !!v;
    }
    if (binding.literalString !== undefined) return !!binding.literalString;
    return false;
  }

  // ---- Common Props ----
  function applyCommonProps(el, props, globalData) {
    if (props.width !== undefined)
      el.style.width = typeof props.width === 'number' ? props.width + '%' : props.width;
    if (props.height !== undefined)
      el.style.height = typeof props.height === 'number' ? props.height + '%' : props.height;
    if (props.minWidth !== undefined)
      el.style.minWidth = typeof props.minWidth === 'number' ? props.minWidth + 'px' : props.minWidth;
    if (props.minHeight !== undefined)
      el.style.minHeight = typeof props.minHeight === 'number' ? props.minHeight + 'px' : props.minHeight;

    if (props.padding !== undefined) applySpacing(el, 'padding', props.padding);
    if (props.margin !== undefined) applySpacing(el, 'margin', props.margin);

    if (props.backgroundColor) el.style.backgroundColor = props.backgroundColor;

    if (props.borderRadius) {
      el.style.borderRadius = BORDER_RADIUS_MAP[props.borderRadius] ||
        (typeof props.borderRadius === 'number' ? props.borderRadius + 'px' : props.borderRadius);
    }

    if (props.position) el.style.position = props.position;
    if (props.zIndex !== undefined) el.style.zIndex = String(props.zIndex);
    if (props.flex !== undefined) el.style.flex = String(props.flex);
    if (props.flexWrap) el.style.flexWrap = props.flexWrap;
    if (props.boxSizing) el.style.boxSizing = props.boxSizing;

    if (props.border) applyBorder(el, props.border);
    if (props.boxShadow) applyBoxShadow(el, props.boxShadow);

    if (props.hide) {
      if (resolveBoolean(props.hide, globalData)) {
        el.style.display = 'none';
      }
    }
  }

  function applySpacing(el, prop, value) {
    if (Array.isArray(value) && value.length === 4) {
      el.style[prop] = value.map(function (v) {
        return typeof v === 'number' ? v + 'px' : v;
      }).join(' ');
    } else if (typeof value === 'number') {
      el.style[prop] = value + 'px';
    } else if (typeof value === 'string') {
      el.style[prop] = value;
    }
  }

  function applyBorder(el, border) {
    if (Array.isArray(border) && border.length === 4) {
      var sides = ['Top', 'Right', 'Bottom', 'Left'];
      for (var i = 0; i < 4; i++) {
        var b = border[i];
        if (!b) continue;
        var w = (b.width || 1) + 'px';
        var s = b.type === 'dash' ? 'dashed' : (b.type || 'solid');
        var c = b.color || '#E5E5E5';
        el.style['border' + sides[i]] = w + ' ' + s + ' ' + c;
      }
    } else if (border && typeof border === 'object') {
      var bw = (border.width || 1) + 'px';
      var bs = border.type === 'dash' ? 'dashed' : (border.type || 'solid');
      var bc = border.color || '#E5E5E5';
      el.style.border = bw + ' ' + bs + ' ' + bc;
    }
  }

  function applyBoxShadow(el, shadow) {
    var shadows = Array.isArray(shadow) ? shadow : [shadow];
    var parts = shadows.map(function (s) {
      var h = (s.hOffset || 0) + 'px';
      var v = (s.vOffset || 0) + 'px';
      var blur = (s.blurRadius || 0) + 'px';
      var spread = (s.spreadRadius || 0) + 'px';
      var color = s.color || 'rgba(0,0,0,0.1)';
      return h + ' ' + v + ' ' + blur + ' ' + spread + ' ' + color;
    });
    el.style.boxShadow = parts.join(', ');
  }

  // ---- Context object passed to renderers ----
  function makeCtx(surface, scopeData, onAction) {
    return {
      compMap: surface.compMap,
      data: surface.data,
      scopeData: scopeData,
      onAction: onAction,
      surface: surface
    };
  }

  // ---- Component Renderers ----

  function renderColumn(props, ctx) {
    var el = document.createElement('div');
    el.style.display = 'flex';
    el.style.flexDirection = 'column';
    if (props.gap !== undefined) el.style.gap = typeof props.gap === 'number' ? props.gap + 'px' : props.gap;
    if (props.alignment) {
      var aMap = { left: 'flex-start', center: 'center', right: 'flex-end', start: 'flex-start', end: 'flex-end' };
      el.style.alignItems = aMap[props.alignment] || props.alignment;
    }
    if (props.distribution) {
      var dMap = { start: 'flex-start', center: 'center', end: 'flex-end', spaceBetween: 'space-between', spaceAround: 'space-around' };
      el.style.justifyContent = dMap[props.distribution] || props.distribution;
    }
    applyCommonProps(el, props, ctx.data);
    el.appendChild(renderChildren(props, ctx));
    return el;
  }

  function renderRow(props, ctx) {
    var el = document.createElement('div');
    el.style.display = 'flex';
    el.style.flexDirection = 'row';
    el.style.alignItems = 'center';
    if (props.gap !== undefined) el.style.gap = typeof props.gap === 'number' ? props.gap + 'px' : props.gap;
    if (props.distribution) {
      var dMap = { start: 'flex-start', center: 'center', end: 'flex-end', spaceBetween: 'space-between', spaceAround: 'space-around' };
      el.style.justifyContent = dMap[props.distribution] || props.distribution;
    }
    if (props.alignment) {
      var aMap = { top: 'flex-start', middle: 'center', bottom: 'flex-end' };
      el.style.alignItems = aMap[props.alignment] || props.alignment;
    }
    applyCommonProps(el, props, ctx.data);
    el.appendChild(renderChildren(props, ctx));
    return el;
  }

  function renderCard(props, ctx) {
    var el = document.createElement('div');
    el.style.display = 'flex';
    el.style.flexDirection = 'column';
    el.style.boxShadow = '0 1px 6px rgba(0,0,0,.08)';
    if (!props.backgroundColor) el.style.backgroundColor = '#FFFFFF';
    if (!props.borderRadius) el.style.borderRadius = '8px';
    if (props.gap !== undefined) el.style.gap = typeof props.gap === 'number' ? props.gap + 'px' : props.gap;
    applyCommonProps(el, props, ctx.data);
    el.appendChild(renderChildren(props, ctx));
    return el;
  }

  function renderText(props, ctx) {
    var el = document.createElement('div');
    el.textContent = resolveValue(props.text, ctx.scopeData, ctx.data);

    if (props.usageHint && USAGE_HINT_STYLES[props.usageHint]) {
      var hint = USAGE_HINT_STYLES[props.usageHint];
      if (hint.color) el.style.color = hint.color;
      if (hint.fontWeight) el.style.fontWeight = hint.fontWeight;
      if (hint.fontSize) el.style.fontSize = hint.fontSize;
      if (hint.textDecoration) el.style.textDecoration = hint.textDecoration;
      if (hint.cursor) el.style.cursor = hint.cursor;
    }

    if (props.size && TEXT_SIZE_MAP[props.size]) el.style.fontSize = TEXT_SIZE_MAP[props.size];
    if (props.color) el.style.color = props.color;
    if (props.fontSize) el.style.fontSize = props.fontSize;
    if (props.fontWeight) el.style.fontWeight = String(props.fontWeight);
    if (props.bold) el.style.fontWeight = 'bold';
    if (props.italic) el.style.fontStyle = 'italic';
    if (props.underline) el.style.textDecoration = 'underline';
    el.style.lineHeight = '1.6';

    if (props.numberOfLines) {
      el.style.display = '-webkit-box';
      el.style.webkitLineClamp = String(props.numberOfLines);
      el.style.webkitBoxOrient = 'vertical';
      el.style.overflow = 'hidden';
    }

    return el;
  }

  function renderRichText(props, ctx) {
    var el = document.createElement('div');
    el.innerHTML = resolveValue(props.text, ctx.scopeData, ctx.data);
    if (props.fontSize) el.style.fontSize = props.fontSize;
    if (props.color) el.style.color = props.color;
    return el;
  }

  function renderButton(props, ctx) {
    var btnType = props.type || 'primary';

    if (btnType === 'custom' && props.child) {
      var wrapper = document.createElement('button');
      wrapper.style.background = 'none';
      wrapper.style.border = 'none';
      wrapper.style.padding = '0';
      wrapper.style.cursor = 'pointer';
      var childEl = renderNode(props.child, ctx);
      if (childEl) wrapper.appendChild(childEl);
      attachButtonBehavior(wrapper, props, ctx);
      applyCommonProps(wrapper, props, ctx.data);
      return wrapper;
    }

    var el = document.createElement('button');
    el.style.padding = '10px 20px';
    el.style.borderRadius = '20px';
    el.style.fontSize = '14px';
    el.style.fontWeight = '500';
    el.style.cursor = 'pointer';
    el.style.transition = 'background .15s, color .15s';
    el.style.display = 'inline-block';

    var typeStyle = BUTTON_TYPE_STYLES[btnType] || BUTTON_TYPE_STYLES.primary;
    el.style.background = typeStyle.background;
    el.style.color = typeStyle.color;
    el.style.border = typeStyle.border;
    if (typeStyle.textDecoration) el.style.textDecoration = typeStyle.textDecoration;

    if (props.size === 'small') {
      el.style.padding = '6px 14px';
      el.style.fontSize = '12px';
    } else if (props.size === 'auto') {
      el.style.padding = '6px 12px';
    }

    if (props.disabled) {
      el.disabled = true;
      el.style.opacity = '0.5';
      el.style.cursor = 'not-allowed';
    }

    el.textContent = resolveValue(props.text, ctx.scopeData, ctx.data);

    if (props.width !== undefined)
      el.style.width = typeof props.width === 'number' ? props.width + '%' : props.width;

    attachButtonBehavior(el, props, ctx);
    return el;
  }

  function attachButtonBehavior(el, props, ctx) {
    if (props.reportAction) {
      el.addEventListener('click', function () {
        handleAction(props.reportAction, ctx);
      });
    }
    if (props.action) {
      el.addEventListener('click', function () {
        if (props.once) {
          el.disabled = true;
          el.style.opacity = '0.5';
          el.style.cursor = 'not-allowed';
        }
        handleAction(props.action, ctx);
      });
    }
  }

  function renderDivider(props, ctx) {
    var isVertical = props.vertical === true;

    if (isVertical) {
      var el = document.createElement('div');
      el.style.display = 'inline-block';
      el.style.width = props.hairline ? '0.5px' : '1px';
      el.style.minHeight = '100%';
      el.style.backgroundColor = props.borderColor || '#E5E5E5';
      if (props.dashed) {
        el.style.backgroundColor = 'transparent';
        el.style.borderLeft = (props.hairline ? '0.5px' : '1px') + ' dashed ' + (props.borderColor || '#E5E5E5');
      }
      if (props.margin) el.style.margin = typeof props.margin === 'number' ? '0 ' + props.margin + 'px' : props.margin;
      return el;
    }

    if (props.description) {
      var wrapper = document.createElement('div');
      wrapper.style.display = 'flex';
      wrapper.style.alignItems = 'center';
      if (props.margin) wrapper.style.margin = typeof props.margin === 'number' ? props.margin + 'px 0' : props.margin;
      if (props.inset) {
        wrapper.style.marginLeft = props.inset;
        wrapper.style.marginRight = props.inset;
      }

      var line1 = document.createElement('div');
      line1.style.flex = '1';
      line1.style.height = props.hairline ? '0.5px' : '1px';
      line1.style.backgroundColor = props.borderColor || '#E5E5E5';
      if (props.dashed) {
        line1.style.backgroundColor = 'transparent';
        line1.style.borderTop = (props.hairline ? '0.5px' : '1px') + ' dashed ' + (props.borderColor || '#E5E5E5');
      }

      var desc = document.createElement('span');
      desc.textContent = props.description;
      desc.style.fontSize = '12px';
      desc.style.color = props.color || '#999';
      var pad = props.padding || '8px';
      desc.style.padding = '0 ' + (typeof pad === 'number' ? pad + 'px' : pad);

      var line2 = line1.cloneNode(true);

      wrapper.appendChild(line1);
      wrapper.appendChild(desc);
      wrapper.appendChild(line2);
      return wrapper;
    }

    var hr = document.createElement('hr');
    hr.style.border = 'none';
    var lineH = props.hairline ? '0.5px' : '1px';
    if (props.dashed) {
      hr.style.borderTop = lineH + ' dashed ' + (props.borderColor || '#E5E5E5');
    } else {
      hr.style.borderTop = lineH + ' solid ' + (props.borderColor || '#E5E5E5');
    }
    if (props.margin) hr.style.margin = typeof props.margin === 'number' ? props.margin + 'px 0' : props.margin;
    else hr.style.margin = '4px 0';
    if (props.inset) {
      hr.style.marginLeft = props.inset;
      hr.style.marginRight = props.inset;
    }
    return hr;
  }

  function renderTag(props, ctx) {
    var el = document.createElement('span');
    el.textContent = resolveValue(props.text, ctx.scopeData, ctx.data);
    el.style.display = 'inline-block';

    var sizePreset = TAG_SIZE_MAP[props.size || 'middle'] || TAG_SIZE_MAP.middle;
    el.style.padding = sizePreset.padding;
    el.style.fontSize = sizePreset.fontSize;
    el.style.borderRadius = '10px';

    if (props.size === 'custom') {
      if (props.fontSize) el.style.fontSize = typeof props.fontSize === 'number' ? props.fontSize + 'px' : props.fontSize;
      if (props.borderRadius) {
        el.style.borderRadius = BORDER_RADIUS_MAP[props.borderRadius] ||
          (typeof props.borderRadius === 'number' ? props.borderRadius + 'px' : props.borderRadius);
      }
    }

    if (props.color) el.style.color = props.color;
    if (props.backgroundColor) {
      el.style.backgroundColor = props.backgroundColor;
    } else {
      el.style.backgroundColor = '#FFF3E0';
      if (!props.color) el.style.color = '#FF6600';
    }
    if (props.borderColor) {
      el.style.border = '1px solid ' + props.borderColor;
    }
    return el;
  }

  function renderImage(props, ctx) {
    var el = document.createElement('img');
    var url = resolveValue(props.url, ctx.scopeData, ctx.data);
    if (url) el.src = url;
    el.alt = '';
    el.style.display = 'block';

    if (props.type === 'avatar') {
      el.style.borderRadius = '50%';
      el.style.aspectRatio = '1 / 1';
      el.style.objectFit = props.fit || 'cover';
      var avatarSizeMap = { small: '32px', middle: '48px', large: '64px', auto: 'auto' };
      var dim = avatarSizeMap[props.size || 'middle'] || props.size || '48px';
      el.style.width = dim;
      el.style.height = dim;
    } else {
      if (props.borderRadius) {
        el.style.borderRadius = BORDER_RADIUS_MAP[props.borderRadius] || props.borderRadius;
      }
      if (props.size) {
        var sMap = { small: '32px', middle: '48px', large: '64px', xlarge: '72px', xxlarge: '88px', auto: 'auto' };
        var d = sMap[props.size] || props.size;
        el.style.width = d;
        el.style.height = d;
      }
      if (props.fit) el.style.objectFit = props.fit;
    }

    if (props.imageWidth !== undefined)
      el.style.width = typeof props.imageWidth === 'number' ? props.imageWidth + 'px' : props.imageWidth;
    if (props.imageHeight !== undefined)
      el.style.height = typeof props.imageHeight === 'number' ? props.imageHeight + 'px' : props.imageHeight;

    applyCommonProps(el, props, ctx.data);
    return el;
  }

  function renderIcon(props, ctx) {
    var el = document.createElement('span');
    el.textContent = resolveValue(props.name, ctx.scopeData, ctx.data) || '\u25CF';
    el.style.display = 'inline-block';
    el.style.textAlign = 'center';

    if (props.size) {
      var dim = ICON_SIZE_MAP[props.size] || props.size;
      el.style.fontSize = dim;
      el.style.width = dim;
      el.style.height = dim;
      el.style.lineHeight = dim;
    }
    if (props.iconWidth !== undefined)
      el.style.width = typeof props.iconWidth === 'number' ? props.iconWidth + 'px' : props.iconWidth;
    if (props.iconHeight !== undefined)
      el.style.height = typeof props.iconHeight === 'number' ? props.iconHeight + 'px' : props.iconHeight;
    if (props.color) el.style.color = props.color;
    return el;
  }

  function renderCircle(props) {
    var el = document.createElement('div');
    el.style.borderRadius = '50%';
    if (props.backgroundColor) el.style.backgroundColor = props.backgroundColor;
    var sizeMap = { small: '6px', middle: '10px', big: '14px' };
    var dim = (typeof props.size === 'number') ? (props.size + 'px') : (sizeMap[props.size] || '10px');
    el.style.width = dim;
    el.style.height = dim;
    el.style.flexShrink = '0';
    return el;
  }

  function renderLine(props) {
    var el = document.createElement('div');
    el.style.height = '2px';
    el.style.minHeight = '2px';
    if (props.backgroundColor) el.style.backgroundColor = props.backgroundColor;
    if (props.borderRadius) {
      el.style.borderRadius = BORDER_RADIUS_MAP[props.borderRadius] ||
        (typeof props.borderRadius === 'number' ? props.borderRadius + 'px' : props.borderRadius);
    }
    return el;
  }

  function renderList(props, ctx) {
    var arr = [];
    if (props.dataSource) {
      if (props.dataSource.path !== undefined) {
        var raw = resolvePath(ctx.data, props.dataSource.path);
        arr = Array.isArray(raw) ? raw : [];
      } else if (props.dataSource.literalString !== undefined) {
        var ls = props.dataSource.literalString;
        arr = Array.isArray(ls) ? ls : [];
      }
    }

    var el = document.createElement('div');
    el.style.display = 'flex';
    el.style.flexDirection = (props.direction === 'horizontal') ? 'row' : 'column';
    if (props.gap !== undefined) el.style.gap = typeof props.gap === 'number' ? props.gap + 'px' : props.gap;
    if (props.alignment) {
      var aMap = { start: 'flex-start', center: 'center', end: 'flex-end' };
      el.style.alignItems = aMap[props.alignment] || props.alignment;
    }
    applyCommonProps(el, props, ctx.data);

    if (arr.length === 0 && props.emptyChild) {
      var emptyCtx = makeCtx(ctx.surface, { item: null }, ctx.onAction);
      var emptyEl = renderNode(props.emptyChild, emptyCtx);
      if (emptyEl) el.appendChild(emptyEl);
    } else {
      arr.forEach(function (item) {
        var itemCtx = makeCtx(ctx.surface, { item: item }, ctx.onAction);
        var childEl = renderNode(props.child, itemCtx);
        if (childEl) el.appendChild(childEl);
      });
    }
    return el;
  }

  function renderTable(props, ctx) {
    var el = document.createElement('div');
    el.style.display = 'grid';
    el.style.gridTemplateColumns = (props.columnWidths && props.columnWidths.length)
      ? props.columnWidths.join(' ')
      : ('1fr '.repeat(props.columnCount || 1)).trim();
    if (props.gap !== undefined) el.style.gap = typeof props.gap === 'number' ? props.gap + 'px' : props.gap;

    if (props.justifyItems) el.style.justifyItems = props.justifyItems;
    if (props.alignItems) el.style.alignItems = props.alignItems;
    if (props.justifyContent) el.style.justifyContent = props.justifyContent;
    if (props.alignContent) el.style.alignContent = props.alignContent;

    applyCommonProps(el, props, ctx.data);

    var mergeMap = {};
    if (props.mergeCells && Array.isArray(props.mergeCells)) {
      props.mergeCells.forEach(function (mc) {
        mergeMap[mc.id] = mc;
      });
    }

    var childIds = (props.children && props.children.explicitList) || [];
    childIds.forEach(function (childId) {
      var childEl = renderNode(childId, ctx);
      if (!childEl) return;
      var merge = mergeMap[childId];
      if (merge) {
        if (merge.row) childEl.style.gridRow = (merge.row.from + 1) + ' / span ' + merge.row.size;
        if (merge.column) childEl.style.gridColumn = (merge.column.from + 1) + ' / span ' + merge.column.size;
      }
      el.appendChild(childEl);
    });

    return el;
  }

  function renderPopup(props, ctx) {
    var overlay = document.createElement('div');
    overlay.style.display = props.modelValue ? 'flex' : 'none';
    overlay.style.position = 'fixed';
    overlay.style.top = '0';
    overlay.style.left = '0';
    overlay.style.right = '0';
    overlay.style.bottom = '0';
    overlay.style.zIndex = String(props.zIndex || 100);

    if (props.overlay) {
      overlay.style.backgroundColor = 'rgba(0,0,0,0.3)';
    }

    var posMap = {
      bottom: { alignItems: 'flex-end', justifyContent: 'center' },
      top: { alignItems: 'flex-start', justifyContent: 'center' },
      left: { alignItems: 'center', justifyContent: 'flex-start' },
      right: { alignItems: 'center', justifyContent: 'flex-end' },
      center: { alignItems: 'center', justifyContent: 'center' }
    };
    var pos = posMap[props.position || 'bottom'] || posMap.bottom;
    overlay.style.alignItems = pos.alignItems;
    overlay.style.justifyContent = pos.justifyContent;

    if (props.closeOnOverlayClick) {
      overlay.addEventListener('click', function (e) {
        if (e.target === overlay) {
          overlay.style.display = 'none';
          if (ctx.onAction) {
            ctx.onAction('popupOpenStatusChange', { isOpen: false });
          }
        }
      });
    }

    var content = document.createElement('div');
    content.style.display = 'flex';
    content.style.flexDirection = 'column';
    content.style.backgroundColor = props.backgroundColor || '#fff';
    if (props.borderRadius) {
      content.style.borderRadius = BORDER_RADIUS_MAP[props.borderRadius] || props.borderRadius;
    }
    if (props.padding !== undefined) applySpacing(content, 'padding', props.padding);
    if (props.width !== undefined)
      content.style.width = typeof props.width === 'number' ? props.width + '%' : props.width;
    content.style.maxHeight = '80vh';
    content.style.overflow = 'auto';
    content.style.position = 'relative';

    if (props.title) {
      var titleEl = document.createElement('div');
      titleEl.textContent = props.title;
      titleEl.style.fontWeight = 'bold';
      titleEl.style.padding = '0 0 8px 0';
      titleEl.style.fontSize = '16px';
      content.appendChild(titleEl);
    }

    if (props.closeable) {
      var closeBtn = document.createElement('button');
      closeBtn.textContent = '\u00D7';
      closeBtn.style.cssText = 'position:absolute;top:8px;right:8px;background:none;border:none;font-size:20px;cursor:pointer;color:#999;';
      closeBtn.onclick = function () {
        overlay.style.display = 'none';
        if (ctx.onAction) ctx.onAction('popupOpenStatusChange', { isOpen: false });
      };
      content.appendChild(closeBtn);
    }

    content.appendChild(renderChildren(props, ctx));
    overlay.appendChild(content);

    overlay._popupComponentId = true;
    return overlay;
  }

  function renderCarInsPolicy(props, ctx) {
    var el = document.createElement('div');
    el.style.cssText = 'border-radius:12px;overflow:hidden;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.08);';

    var header = document.createElement('div');
    header.style.cssText = 'padding:16px;display:flex;align-items:center;gap:12px;background:linear-gradient(135deg,#e8f4fd,#f0f7ff);';
    var plateText = resolveValue(props.licenseNum, ctx.scopeData, ctx.data) || '未知车牌';
    var daysLeft = resolveValue(props.leftDays, ctx.scopeData, ctx.data) || '?';
    header.innerHTML = '<div style="font-size:18px;font-weight:bold;">' + escHtml(plateText) + '</div>' +
      '<div style="margin-left:auto;text-align:right;"><div style="font-size:24px;font-weight:bold;color:#f0762b;">' + escHtml(String(daysLeft)) + '</div><div style="font-size:12px;color:#999;">剩余天数</div></div>';
    el.appendChild(header);

    if (props.nextRenewalDate) {
      var renewalDate = resolveValue(props.nextRenewalDate, ctx.scopeData, ctx.data);
      if (renewalDate) {
        var renewalEl = document.createElement('div');
        renewalEl.style.cssText = 'padding:8px 16px;font-size:12px;color:#666;background:#fffbe6;';
        renewalEl.textContent = '下次可续保日期: ' + renewalDate;
        el.appendChild(renewalEl);
      }
    }

    var body = document.createElement('div');
    body.style.cssText = 'padding:12px 16px;display:flex;flex-direction:column;gap:8px;';
    var info = props.policyInfo || {};
    var rows = [
      { label: '商业险', data: info.bizApply },
      { label: '交强险', data: info.forceApply },
      { label: '驾乘险', data: info.ppiInfo }
    ];
    rows.forEach(function (r) {
      if (!r.data) return;
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;justify-content:space-between;padding:4px 0;';
      var date = r.data.invalidDate ? resolveValue(r.data.invalidDate, ctx.scopeData, ctx.data) : '-';
      row.innerHTML = '<span style="color:#666;">' + escHtml(r.label) + '</span><span>' + escHtml(date || '-') + ' 到期</span>';
      body.appendChild(row);
    });
    el.appendChild(body);

    if (props.action) {
      var btn = document.createElement('button');
      btn.style.cssText = 'margin:0 16px 16px;padding:10px;background:#f0762b;color:#fff;border:none;border-radius:8px;font-size:14px;cursor:pointer;';
      btn.textContent = '立即续保';
      btn.addEventListener('click', function () { handleAction(props.action, ctx); });
      el.appendChild(btn);
    }

    return el;
  }

  function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  var RENDERERS = {
    Column: renderColumn,
    Row: renderRow,
    Card: renderCard,
    Text: renderText,
    RichText: renderRichText,
    Button: renderButton,
    Divider: renderDivider,
    Tag: renderTag,
    Image: renderImage,
    Icon: renderIcon,
    Circle: renderCircle,
    Line: renderLine,
    List: renderList,
    Table: renderTable,
    Popup: renderPopup,
    CarInsPolicy: renderCarInsPolicy
  };

  function renderNode(compId, ctx) {
    var compDef = ctx.compMap.get(compId);
    if (!compDef) return null;
    var type = Object.keys(compDef)[0];
    var props = compDef[type] || {};
    var renderer = RENDERERS[type];
    if (!renderer) {
      console.warn('[A2UI] Unsupported component:', type);
      var el = document.createElement('div');
      el.style.cssText = 'font-size:11px;color:#999;padding:2px 0';
      el.textContent = '[unknown: ' + type + ']';
      return el;
    }
    return renderer(props, ctx);
  }

  function renderChildren(props, ctx) {
    var frag = document.createDocumentFragment();
    var ids = (props.children && props.children.explicitList) || [];
    ids.forEach(function (childId) {
      var childEl = renderNode(childId, ctx);
      if (childEl) frag.appendChild(childEl);
    });
    return frag;
  }

  // ---- Action Handling ----
  function handleAction(action, ctx) {
    if (!action) return;
    var name = action.name;
    var args = resolveActionArgs(action.args, ctx);

    switch (name) {
      case 'openLink':
        if (ctx.onAction) ctx.onAction('openLink', args);
        break;
      case 'query':
        if (ctx.onAction) ctx.onAction('query', args);
        break;
      case 'report':
        if (ctx.onAction) ctx.onAction('report', args);
        break;
      case 'openPopup':
        if (args && args.popupComponentId) {
          openPopupById(ctx.surface, args.popupComponentId);
        }
        if (ctx.onAction) ctx.onAction('openPopup', args);
        break;
      case 'closePopup':
        if (args && args.popupComponentId) {
          closePopupById(ctx.surface, args.popupComponentId);
        }
        if (ctx.onAction) ctx.onAction('closePopup', args);
        break;
      case 'sendRequest':
        if (ctx.onAction) ctx.onAction('sendRequest', args);
        break;
      default:
        if (ctx.onAction) ctx.onAction(name, args);
    }
  }

  function resolveActionArgs(argsBinding, ctx) {
    if (!argsBinding) return {};
    if (argsBinding.literalString !== undefined) {
      return argsBinding.literalString;
    }
    if (argsBinding.path !== undefined) {
      var v = resolvePath(ctx.data, argsBinding.path);
      if (v === undefined && ctx.scopeData) {
        v = resolvePath(ctx.scopeData, argsBinding.path);
      }
      return v || {};
    }
    return {};
  }

  function openPopupById(surface, compId) {
    if (!surface || !surface.rootEl) return;
    var popups = surface.rootEl.querySelectorAll('[data-popup-id="' + compId + '"]');
    popups.forEach(function (el) { el.style.display = 'flex'; });
  }

  function closePopupById(surface, compId) {
    if (!surface || !surface.rootEl) return;
    var popups = surface.rootEl.querySelectorAll('[data-popup-id="' + compId + '"]');
    popups.forEach(function (el) { el.style.display = 'none'; });
  }

  // ---- Surface Lifecycle ----
  function buildCompMap(components) {
    var map = new Map();
    (components || []).forEach(function (c) {
      map.set(c.id, c.component);
    });
    return map;
  }

  function handleBeginRendering(container, payload, options) {
    var surfaceId = payload.surfaceId;
    var onAction = (options && options.onAction) || function () {};

    var existing = surfaces.get(surfaceId);
    if (existing && existing.rootEl && existing.rootEl.parentNode) {
      existing.rootEl.parentNode.removeChild(existing.rootEl);
    }

    var surface = {
      id: surfaceId,
      rootEl: null,
      compMap: buildCompMap(payload.components),
      data: payload.data || {},
      rootComponentId: payload.rootComponentId,
      container: container,
      onAction: onAction
    };
    surfaces.set(surfaceId, surface);

    var wrapper = document.createElement('div');
    wrapper.style.width = '100%';
    wrapper.setAttribute('data-surface-id', surfaceId);
    surface.rootEl = wrapper;

    var ctx = makeCtx(surface, null, onAction);
    var root = renderNode(payload.rootComponentId, ctx);
    if (root) wrapper.appendChild(root);

    tagPopups(wrapper, surface.compMap);

    container.appendChild(wrapper);
    return wrapper;
  }

  function tagPopups(rootEl, compMap) {
    compMap.forEach(function (compDef, compId) {
      var type = Object.keys(compDef)[0];
      if (type === 'Popup') {
        var popups = rootEl.querySelectorAll('div');
        popups.forEach(function (el) {
          if (el._popupComponentId) {
            el.setAttribute('data-popup-id', compId);
            delete el._popupComponentId;
          }
        });
      }
    });
  }

  function handleSurfaceUpdate(payload) {
    var surfaceId = payload.surfaceId;
    var surface = surfaces.get(surfaceId);
    if (!surface) {
      console.warn('[A2UI] surfaceUpdate: unknown surface', surfaceId);
      return;
    }

    var newMap = buildCompMap(payload.components);
    newMap.forEach(function (comp, id) {
      surface.compMap.set(id, comp);
    });

    reRenderSurface(surface);
  }

  function handleDataModelUpdate(payload) {
    var surfaceId = payload.surfaceId;
    var surface = surfaces.get(surfaceId);
    if (!surface) {
      console.warn('[A2UI] dataModelUpdate: unknown surface', surfaceId);
      return;
    }

    var newData = payload.data || {};
    Object.keys(newData).forEach(function (k) {
      surface.data[k] = newData[k];
    });

    reRenderSurface(surface);
  }

  function handleDeleteSurface(payload) {
    var surfaceId = payload.surfaceId;
    var surface = surfaces.get(surfaceId);
    if (!surface) return;

    if (surface.rootEl && surface.rootEl.parentNode) {
      surface.rootEl.parentNode.removeChild(surface.rootEl);
    }
    surfaces.delete(surfaceId);
  }

  function reRenderSurface(surface) {
    if (!surface.rootEl) return;
    surface.rootEl.innerHTML = '';
    var ctx = makeCtx(surface, null, surface.onAction);
    var root = renderNode(surface.rootComponentId, ctx);
    if (root) surface.rootEl.appendChild(root);
    tagPopups(surface.rootEl, surface.compMap);
  }

  // ---- Public API ----
  window.A2UIRenderer = {
    render: function (container, payload, options) {
      var event = payload.event || 'beginRendering';
      switch (event) {
        case 'beginRendering':
          return handleBeginRendering(container, payload, options);
        case 'surfaceUpdate':
          return handleSurfaceUpdate(payload);
        case 'dataModelUpdate':
          return handleDataModelUpdate(payload);
        case 'deleteSurface':
          return handleDeleteSurface(payload);
        default:
          console.warn('[A2UI] Unknown event:', event);
      }
    },

    getSurface: function (surfaceId) {
      return surfaces.get(surfaceId);
    },

    destroySurface: function (surfaceId) {
      var surface = surfaces.get(surfaceId);
      if (!surface) return;
      if (surface.rootEl && surface.rootEl.parentNode) {
        surface.rootEl.parentNode.removeChild(surface.rootEl);
      }
      surfaces.delete(surfaceId);
    },

    destroyAll: function () {
      surfaces.forEach(function (surface) {
        if (surface.rootEl && surface.rootEl.parentNode) {
          surface.rootEl.parentNode.removeChild(surface.rootEl);
        }
      });
      surfaces.clear();
    }
  };
})();
