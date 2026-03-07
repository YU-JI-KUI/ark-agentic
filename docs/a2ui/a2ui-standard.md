## 1 数据格式

```json
{
  "event": "beginRendering",
  "version": "1.0.0",
  "surfaceId": "test-001",
  "rootComponentId": "root-001",
  "components": [],
  "catalogId": "",
  "style": "default",
  "data": {},
  "hideVoteRecorder": false,
  "exposureData": {
    "eventId": "test-event",
    "eventName": "测试事件",
    "eventData": { "name": 123 }
  }
}
```

- event: 可选，操作事件类型，用于区分是什么样的操作，初始绘制、更新绘制、数据更新等，默认为：beginRendering
  - beginRendering: 初始绘制（画布）
  - surfaceUpdate: 更新绘制（画布），更新或增加组件
  - dataModelUpdate: 更新数据
  - deleteSurface: 移除画布
- version: 可选，协议版本号，默认为：1.0.0
- surfaceId: 必填，绘制画布id，用来唯一标识一个画布，绘制的更新、移除，数据的绑定都是基于该id
- rootComponentId: 根组件id
- components: 绘制的组件列表，与catalogId互斥，surfaceUpdate更新绘制时必须携带，beginRendering初始绘制时components和catalogId任选其一
- catalogId: 模版id，预制的模版id,与components互斥，beginRendering初始绘制时components和catalogId任选其一
- style: 卡片显示的样式，默认为default，后续扩展，仅在beginRendering初始绘制时携带
- data: 组件中绑定的数据，dataModelUpdate数据更新时必须携带
- hideVoteRecorder: 是否隐藏卡片上的点赞和点踩，仅在beginRendering初始绘制时携带
- exposureData: 需要曝光的事件，可选
  - eventId: 上报的事件id
  - eventName: 上报的事件名称
  - eventData: 需要上报的事件参数，Record<string, string | number | boolean>类型

### 1.1 初始化画布

不使用模版

```json
{
  "event": "beginRendering",
  "version": "1.0.0",
  "surfaceId": "surface-01",
  "rootComponentId": "root-001",
  "components": [
    {
      "id": "root-001",
      "component": {
        "Column": {
          "alignment": "center",
          "distribution": "start",
          "children": {
            "explicitList": ["text-001"]
          }
        }
      }
    },
    {
      "id": "text-001",
      "component": {
        "Text": {
          "text": { "path": "infoText", "literalString": "默认文本" },
          "usageHint": "info",
          "bold": false,
          "size": "normal"
        }
      }
    }
  ],
  "style": "default",
  "hideVoteRecorder": false,
  "data": {
    "infoText": "这是一段测试文本"
  },
  "exposureData": {
    "eventId": "test-event",
    "eventName": "测试事件",
    "eventData": { "name": 123 }
  }
}
```

## 2 组件定义与说明

### 2.1 公共参数说明

#### 2.1.1 组件公共属性

所有原子组件都具备的属性

- position: 可选，定位类型
  - absolute: 脱离文档流，使用绝对定位
  - relative: 不脱离文档流，使用相对定位
- zIndex: 可选，number类型，层级，默认为2
- width: 可选，number类型，0~100，表示宽度，值为百分比，例如 100，表示width为100%
- height: 可选，number类型，0~100，表示高度，值为百分比，例如 100，表示height为100%
- minWidth: 可选，number或string类型，最小宽度
- minHeight: 可选，number或string类型，最小高度
- flex: 可选，number类型，对应flex布局中的flex属性
- flexWrap: 可选，换行属性
  - nowrap: 不换行
  - wrap: 在需要时换行
- hide: 可选，控制组件是否不展示，用于根据数据判断组件是否显示
  - literalString: 可选，boolean类型，默认值
  - path: 可选，string类型，数据路径，用于动态判断是否隐藏
- boxShadow: 可选，阴影效果，可以是单个阴影对象或阴影数组
  - hOffset: number类型，水平阴影的位置，正值向右偏移，负值向左偏移
  - vOffset: number类型，垂直阴影的位置，正值向下偏移，负值向上偏移
  - blurRadius: 可选，number类型，阴影的模糊半径，值越大阴影边缘越模糊
  - spreadRadius: 可选，number类型，阴影的扩展半径，正值扩大阴影，负值缩小阴影
  - color: string类型，阴影颜色，使用#fff、#ffffff或#ffffffff格式
- boxSizing: 可选，盒模型类型
  - border-box: 包含边框和内边距
  - content-box: 不包含边框和内边距

#### 2.1.2 事件说明

目前定义了多种交互事件，包括链接跳转、发起问询、数据上报、弹窗操作等

- openLink: 链接跳转操作，参数如下：
  - url: string类型，必选，跳转的链接
- query: 发起用户问询，参数如下：
  - queryMsg: string类型，必选，发起的用户问题
  - extendObj: object类型，可选，额外的参数
  - isQueryHide: boolean类型，可选，是否不将问题展示到屏幕上
  - payload: object类型，可选，额外的参数，传递到sse chat接口的extrainfo参数中
- report: 数据上报操作，参数如下：
  - eventId: string类型，必选，事件上报的id
  - eventName: string类型，必选，事件上报的名称
  - eventType: enum类型，必选，上报类型，可选值如下：
    - exposure (曝光)
    - click (点击)
  - eventData: object类型，必选，事件上报的数据
- openPopup: 开启底部弹窗操作，参数如下：
  - popupComponentId: string类型，必选，弹窗的组件id
  - data: object类型，可选，携带的数据
- closePopup: 关闭底部弹窗操作，参数如下：
  - popupComponentId: string类型，必选，弹窗的组件id
- popupOpenStatusChange: popup弹窗显示状态变更事件，参数如下：
  - isOpen: boolean类型，可选，弹窗是否打开
- sendRequest: 发送请求操作，参数如下：
  - url: string类型，必选，请求的url或路径
  - method: string类型，可选，请求方式，POST、GET等，默认为POST
  - headers: object类型，可选，请求头
  - params: object类型，可选，请求的参数

### 2.2 Layout布局组件

#### 2.2.1 RowComponent

行组件，其内部的元素呈水平排列

```json
{
  "Row": {
    "width": 100,
    "alignment": "top",
    "distribution": "start",
    "padding": 32,
    "backgroundColor": "#fff",
    "borderRadius": "small",
    "gap": 20,
    "children": {
      "explicitList": ["text-1"]
    }
  }
}
```

- alignment: 可选，行内元素在垂直方向上的对齐方式，默认为top
  - top: 居上
  - middle: 居中
  - bottom: 底部
- distribution: 可选，行内元素的排列方式，默认为start
  - start: 元素从行首开始排列
  - center: 元素在行中居中排列
  - end: 元素从行尾开始排列
  - spaceBetween: 元素在行内等距分布，首尾元素分别靠边
  - spaceAround: 元素在行内等距分布，首尾元素与边距相等
- padding: 可选，间距，单值或一个长度为4的数组；为单值时，上下左右的间距都为该值；为数组时，按序为上下左右的间距；默认为0
- backgroundColor: 可选，背景色，#fff或#ffffff或#ffffffff格式的16进制颜色值
- borderRadius: 可选，圆角大小，不填则不显示圆角
  - big: 大圆角
  - middle: 中等圆角
  - small: 小圆角
- gap: 可选，行内元素之间的间距，默认为20
- border: 可选，边框样式，可以是单个对象或长度为4的数组（按序为上、右、下、左边框）
  - color: 可选，边框颜色，#fff或#ffffff或#ffffffff格式的16进制颜色值
  - width: 可选，边框线条大小
  - type: 可选，边框的样式，默认为solid
    - solid: 实线边框
    - dash: 虚线边框
- children: 必选，行内的子组件
  - explicitList: 子组件的id列表

#### 2.2.2 ColumnComponent

列组件，其内部的元素呈垂直排列

```json
{
  "Column": {
    "width": 100,
    "alignment": "left",
    "distribution": "start",
    "padding": 32,
    "backgroundColor": "#fff",
    "borderRadius": "small",
    "gap": 20,
    "children": {
      "explicitList": ["text-1", "image-1"]
    }
  }
}
```

- alignment: 可选，列内元素在水平方向上的对齐方式，默认为left
  - left: 靠左对齐
  - center: 居中对齐
  - right: 靠右对齐
- distribution: 可选，列内元素的排列方式，默认为start
  - start: 元素从列首开始排列
  - center: 元素在列中居中排列
  - end: 元素从列尾开始排列
  - spaceBetween: 元素在列内等距分布，首尾元素分别靠边
  - spaceAround: 元素在列内等距分布，首尾元素与边距相等
- padding: 可选，间距，单值或一个长度为4的数组；为单值时，上下左右的间距都为该值；为数组时，按序为上下左右的间距；默认为32
- backgroundColor: 可选，背景色，#fff或#ffffff或#ffffffff格式的16进制颜色值
- borderRadius: 可选，圆角大小，不填则不显示圆角
  - big: 大圆角
  - middle: 中等圆角
  - small: 小圆角
- gap: 可选，列内元素之间的间距，默认为20
- border: 可选，边框样式，可以是单个对象或长度为4的数组（按序为上、右、下、左边框）
  - color: 可选，边框颜色，#fff或#ffffff或#ffffffff格式的16进制颜色值
  - width: 可选，边框线条大小
  - type: 可选，边框的样式，默认为solid
    - solid: 实线边框
    - dash: 虚线边框
- children: 必选，列内的子组件
  - explicitList: 子组件的id列表

### 2.3 容器类组件

#### 2.3.1 CardComponent

卡片组件，用于包裹内容的容器

```json
{
  "Card": {
    "width": 100,
    "borderRadius": "small",
    "padding": 32,
    "margin": 32,
    "backgroundColor": "#fff",
    "children": {
      "explicitList": ["text-1"]
    }
  }
}
```

- borderRadius: 可选，圆角大小，不填则不显示圆角
  - big: 大圆角
  - middle: 中等圆角
  - small: 小圆角
- padding: 可选，间距，单值或一个长度为4的数组；为单值时，上下左右的间距都为该值；为数组时，按序为上下左右的间距；默认为32
- margin: 可选，间距，单值或一个长度为4的数组；为单值时，上下左右的间距都为该值；为数组时，按序为上下左右的间距；默认为32
- backgroundColor: 可选，背景色，#fff或#ffffff或#ffffffff格式的16进制颜色值
- border: 可选，边框样式，可以是单个对象或长度为4的数组（按序为上、右、下、左边框）
  - color: 可选，边框颜色，#fff或#ffffff或#ffffffff格式的16进制颜色值
  - width: 可选，边框线条大小
  - type: 可选，边框的样式，默认为solid
    - solid: 实线边框
    - dash: 虚线边框
- children: 必选，卡片内的子组件
- explicitList: 子组件的id列表

#### 2.3.2 ListComponent

列表组件，用于展示数据列表

```json
{
  "List": {
    "width": 100,
    "borderRadius": "small",
    "padding": 0,
    "backgroundColor": "#fff",
    "direction": "vertical",
    "gap": 10,
    "alignment": "center",
    "child": "list-item-1",
    "dataSource": {
      "literalString": ["item1", "item2", "item3"]
    },
    "emptyChild": "empty-text"
  }
}
```

- borderRadius: 可选，圆角大小，不填则不显示圆角
  - big: 大圆角
  - middle: 中等圆角
  - small: 小圆角
- padding: 可选，间距，单值或一个长度为4的数组；为单值时，上下左右的间距都为该值；为数组时，按序为上下左右的间距；默认为0
- backgroundColor: 可选，背景色，#fff或#ffffff或#ffffffff格式的16进制颜色值
- border: 可选，边框样式，可以是单个对象或长度为4的数组（按序为上、右、下、左边框）
  - color: 可选，边框颜色，#fff或#ffffff或#ffffffff格式的16进制颜色值
  - width: 可选，边框线条大小
  - type: 可选，边框的样式，默认为solid
    - solid: 实线边框
    - dash: 虚线边框
- direction: 可选，子元素的排列方向，默认为vertical
  - horizontal: 横向排列
  - vertical: 纵向排列
- gap: 可选，列表子项之间的间距
- alignment: 可选，子元素的对齐方式，默认为center
  - start: 居上（横向排列时）或居左（纵向排列时）
  - center: 居中
  - end: 居下（横向排列时）或居右（纵向排列时）
- child: 必选，子元素的组件id
- dataSource: 必选，数据项
  - literalString: 静态数据数组
  - path: 数据路径
- emptyChild: 可选，当前数据为空时，展示的组件id

#### 2.3.3 TableComponent

表格组件，用于展示表格数据

```json
{
  "Table": {
    "width": 100,
    "borderRadius": "small",
    "backgroundColor": "#fff",
    "gap": 0,
    "columnCount": 3,
    "columnWidths": ["100px", "1fr", "auto"],
    "mergeCells": [
      {
        "id": "cell-1",
        "row": {
          "from": 0,
          "size": 2
        }
      }
    ],
    "justifyItems": "stretch",
    "alignItems": "stretch",
    "justifyContent": "start",
    "alignContent": "start",
    "children": {
      "explicitList": ["cell-1", "cell-2", "cell-3"]
    }
  }
}
```

- borderRadius: 可选，圆角大小，不填则不显示圆角
  - big: 大圆角
  - middle: 中等圆角
  - small: 小圆角
- backgroundColor: 可选，背景色，#fff或#ffffff或#ffffffff格式的16进制颜色值
- border: 可选，边框样式，可以是单个对象或长度为4的数组（按序为上、右、下、左边框）
  - color: 可选，边框颜色，#fff或#ffffff或#ffffffff格式的16进制颜色值
  - width: 可选，边框线条大小
  - type: 可选，边框的样式，默认为solid
    - solid: 实线边框
    - dash: 虚线边框
- gap: 可选，单元格之间的间距，默认为0
- columnCount: 必选，表格中的列的数量
- columnWidths: 可选，表格中的列宽，格式可以是固定数值表示固定宽度、百分比、fr、auto-fill、auto-fit等
- mergeCells: 可选，合并的行列信息
  - id: 单元格的id
  - row: 可选，合并的行信息
    - from: 开始的行
    - size: 合并的行数
  - column: 可选，合并的列信息
    - from: 开始的列
    - size: 合并的列数
- justifyItems: 可选，单元格内容的水平位置，默认为stretch
  - start: 对齐单元格的起始边缘
  - end: 对齐单元格的结束边缘
  - center: 单元格内部居中
  - stretch: 拉伸，占满单元格的整个宽度
- alignItems: 可选，单元格内容的垂直位置，默认为stretch
  - start: 对齐单元格的起始边缘
  - end: 对齐单元格的结束边缘
  - center: 单元格内部居中
  - stretch: 拉伸，占满单元格的整个高度
- justifyContent: 可选，内容区域在容器里面的水平位置
  - start: 对齐容器的起始边缘
  - end: 对齐容器的结束边缘
  - center: 容器内部居中
  - stretch: 拉伸，占满容器的整个宽度
  - space-around: 元素在容器内等距分布，首尾元素与边距相等
  - space-between: 元素在容器内等距分布，首尾元素分别靠边
  - space-evenly: 元素在容器内均匀分布，所有间距相等
- alignContent: 可选，内容区域在容器里面的垂直位置
  - start: 对齐容器的起始边缘
  - end: 对齐容器的结束边缘
  - center: 容器内部居中
  - stretch: 拉伸，占满容器的整个高度
  - space-around: 元素在容器内等距分布，首尾元素与边距相等
  - space-between: 元素在容器内等距分布，首尾元素分别靠边
  - space-evenly: 元素在容器内均匀分布，所有间距相等
- children: 必选，单元格
  - explicitList: 单元格的id列表

#### 2.3.4 PopupComponent

弹窗组件，用于展示底部弹出式内容

```json
{
  "Popup": {
    "width": 80,
    "borderRadius": "middle",
    "padding": 32,
    "backgroundColor": "#fff",
    "modelValue": false,
    "position": "bottom",
    "overlay": true,
    "closeOnOverlayClick": true,
    "zIndex": 100,
    "title": "弹窗标题",
    "closeable": true,
    "children": {
      "explicitList": ["text-1"]
    }
  }
}
```

- borderRadius: 可选，圆角大小，不填则不显示圆角
  - big: 大圆角
  - middle: 中等圆角
  - small: 小圆角
- padding: 可选，间距，单值或一个长度为4的数组；为单值时，上下左右的间距都为该值；为数组时，按序为上下左右的间距；默认为32
- backgroundColor: 可选，背景色，#fff或#ffffff或#ffffffff格式的16进制颜色值
- modelValue: 可选，boolean类型，弹窗是否显示
- position: 可选，弹窗位置
  - top: 顶部弹出
  - bottom: 底部弹出
  - left: 左侧弹出
  - right: 右侧弹出
  - center: 居中弹出
- overlay: 可选，boolean类型，是否显示遮罩层
- closeOnOverlayClick: 可选，boolean类型，点击遮罩层是否关闭弹窗
- zIndex: 可选，number类型，弹窗的层级
- title: 可选，string类型，弹窗标题
- closeable: 可选，boolean类型，是否显示关闭按钮
- children: 必选，弹窗内的子组件
  - explicitList: 子组件的id列表

### 2.4 Content内容组件

#### 2.4.1 TextComponent

文本组件，用于展示静态或动态文本内容

```json
{
  "Text": {
    "text": {
      "literalString": "这是一个文本"
    },
    "usageHint": "info",
    "bold": false,
    "size": "normal"
  }
}
```

- text: 必选，文本内容
  - literalString: 静态文本值，相当于默认值
  - path: 绑定数据源路径（如：data.user.name），动态获取文本
- usageHint: 可选，文本用途提示，用于控制样式，默认info
  - error: 错误提示文本，通常为红色
  - warning: 警告文本，通常为橙色
  - tips: 提示文本，通常为浅灰（#a4a4a4）
  - info: 普通内容文本，通常为黑色
  - title: 标题文本，通常为加粗大字号
  - link: 可点击链接文本，通常带下划线
- bold: 可选，是否加粗，默认为false
- size: 可选，文字大小，默认为normal
  - xsmall: 极小
  - small: 小字号
  - normal: 默认字号
  - large: 大字号
  - xlarge: 极大
  - xxlarge: 超大
- color: 可选，文本颜色，#fff或#ffffff或#ffffffff格式的16进制颜色值
- fontWeight: 可选，文本粗细，数值类型
- fontSize: 可选，文本大小，如"18px"
- numberOfLines: 可选，文本显示的行数，默认不限制

#### 2.4.2 RichTextComponent

富文本组件，支持复杂文本格式渲染（如HTML标签、样式等）

```json
{
  "RichText": {
    "text": {
      "literalString": "<span style='color: red;'>这是红色文本</span>"
    }
  }
}
```

- text: 必选，富文本内容
  - literalString: 默认显示的富文本字符串（支持HTML标签）
  - path: 绑定数据源路径，动态获取富文本内容

#### 2.4.3 ImageComponent

图片组件，用于展示静态或动态图片

```json
{
  "Image": {
    "url": {
      "literalString": "[https://example.com/image.png](https://example.com/image.png)"
    },
    "borderRadius": "middle",
    "type": "image",
    "size": "auto",
    "fit": "cover"
  }
}
```

- url: 必选，图片链接
  - literalString: 静态图片链接字符串
  - path: 绑定数据源路径，动态获取图片URL
- borderRadius: 可选，圆角大小，不配置则无圆角，type为avatar时无效
  - big: 大圆角
  - middle: 中等圆角
  - small: 小圆角
- type: 可选，图片类型，决定默认样式和行为
  - avatar: 头像类型，通常为圆形或方形
  - image: 普通图片类型
- size: 可选，图片显示大小
  - small: 小尺寸
  - middle: 中等尺寸（type为avatar时默认）
  - large: 大尺寸
  - auto: 自适应大小（type为image时默认）
- imageWidth: 可选，图片宽度
- imageHeight: 可选，图片高度
- fit: 可选，图片填充方式，默认为cover，仅对type为avatar时生效
  - contain: 保持图片比例，完整显示
  - cover: 保持比例，填满容器，可能裁剪
  - fill: 拉伸填充，可能变形
  - scale-down: 按比例缩小，不超过原始尺寸
  - none: 不缩放，保持原始大小

#### 2.4.4 IconComponent

图标组件，用于展示系统或自定义图标

```json
{
  "Icon": {
    "name": {
      "literalString": "icon-user"
    },
    "size": "middle"
  }
}
```

- name: 必选，图标名称，根据名称显示不同的图标
  - literalString: 图标名称字符串（如：icon-user）
  - path: 绑定数据源路径，动态获取图标名称
- size: 可选，图标大小，默认为middle
  - xsmall: 32x32
  - small: 40x40
  - middle: 48x48
  - large: 56x56
  - xlarge: 72x72
  - xxlarge: 88x88
- color: 可选，图标的颜色
- iconWidth: 可选，图标宽度，number或string类型
- iconHeight: 可选，图标高度，number或string类型

#### 2.4.5 TagComponent

标签组件，用于展示标签

```json
{
  "Tag": {
    "text": { "literalString": "财产险" },
    "color": "#6cb585",
    "borderColor": "#6cb585",
    "size": "small"
  }
}
```

- text: 必选，标签展示的文案
  - literalString: 标签文本字符串
  - path: 绑定数据源路径，动态获取标签文本
- backgroundColor: 可选，背景色，使用16进制颜色值，如#fff,#ffffff
- borderColor: 可选，标签的边框颜色，使用16进制颜色值，如#fff,#ffffff；不存在时，取文本颜色
- color: 可选，标签文本的颜色，使用16进制颜色值，如#fff,#ffffff；默认为#6cb585
- size: 可选，标签大小，默认为middle
  - small: 小标签
  - middle: 中标签
  - large: 大标签
  - custom: 自定义
- fontSize: 可选，字体大小，当size为custom时生效
- borderRadius: 可选，圆角大小，当size为custom时生效

#### 2.4.6 CircleComponent

圆点组件，用于显示圆点

```json
{
  "Circle": {
    "backgroundColor": "#ff0000",
    "size": "middle"
  }
}
```

- backgroundColor: 可选，背景色，#fff或#ffffff或#ffffffff格式的16进制颜色值
- size: 可选，圆点大小，默认为middle
  - small: 小
  - middle: 中
  - big: 大
  - number: 自定义圆点宽度（数字类型）

#### 2.4.7 DividerComponent

分割线组件，用于显示分割线

```json
{
  "Divider": {
    "inset": "-36px",
    "description": "分割线描述",
    "margin": "16px",
    "dashed": false,
    "hairline": false,
    "vertical": false,
    "borderColor": "#ddd",
    "color": "#999",
    "padding": "8px"
  }
}
```

- inset: 可选，设置两端缩进距离，正负号可控制缩进方向，如-36px，仅限水平模式
- description: 可选，分割线描述文字，仅限水平模式
- margin: 可选，分割线与上下元素的间距，默认为0
- dashed: 可选，是否为虚线，默认为false
- hairline: 可选，是否为0.5px分割线，默认为false
- vertical: 可选，是否为垂直分割线，默认为false
- borderColor: 可选，线条颜色，#fff或#ffffff或#ffffffff格式的16进制颜色值
- color: 可选，文本颜色，#fff或#ffffff或#ffffffff格式的16进制颜色值
- padding: 可选，文本与线条的间距，默认为0

#### 2.4.8 LineComponent

线条修饰组件，用于显示线条装饰

```json
{
  "Line": {
    "borderRadius": "middle",
    "backgroundColor": "#e0e0e0"
  }
}
```

- borderRadius: 可选，圆角大小
  - big: 大圆角
  - middle: 中等圆角
  - small: 小圆角
  - number: 自定义圆角大小（数字类型）
- backgroundColor: 可选，背景色，#fff或#ffffff或#ffffffff格式的16进制颜色值

### 2.5 交互类组件

#### 2.5.1 ButtonComponent

按钮组件，支持多种样式和交互行为

```json
{
  "Button": {
    "type": "secondary",
    "size": "large",
    "disabled": false,
    "text": {
      "literalString": "点击我"
    },
    "action": {
      "name": "openLink",
      "args": {
        "literalString": { "url": "[https://www.example.com](https://www.example.com)" }
      }
    }
  }
}
```

- type: 可选，按钮样式类型，默认为primary
  - primary: 主要按钮（实心橙色）
  - secondary: 次要按钮（线框橙色）
  - soft: 柔和按钮（浅橙）
  - normal: 普通按钮（线框灰色）
  - info: 文字按钮
  - custom: 自定义按钮，需通过child指定内部内容
- size: 可选，按钮大小，仅当type不为custom时有效，默认为large
  - large: 大按钮
  - small: 小按钮
  - auto: 根据内容自适应
- once: 可选，是否一次性点击，点击后按钮变为disabled状态，默认为false
- disabled: 可选，是否禁用按钮，默认为false
- text: 可选，按钮文本（仅当type不为custom时必填）
  - literalString: 默认文本
  - path: 绑定数据源路径，动态获取文本
- child: 可选，按钮内部元素ID（仅当type为custom时必填）
- reportAction: 可选，数据上报操作，用于埋点统计
  - name: 操作类型，固定为"report"
  - args: 操作参数
    - literalString: 可选，参数值对象
    - path: 可选，参数对应的数据id
- action: 必选，按钮点击后执行的动作，参考5.1.2公共参数中的事件说明

### 2.6 自定义特色组件

#### 2.6.1 CarInsPolicyComponent

车险预览组件，用于展示车险保单信息和续保提醒

```json
{
  "CarInsPolicy": {
    "licenseNum": { "literalString": "粤B-88888", "path": "xxx" },
    "leftDays": { "path": "xxx" },
    "nextRenewalDate": { "path": "xxx" },
    "policyInfo": {
      "bizApply": {
        "invalidDate": { "literalString": "2026-10-28", "path": "xxx" }
      },
      "forceApply": {
        "invalidDate": { "literalString": "2026-10-28", "path": "xxx" }
      },
      "ppiInfo": {
        "invalidDate": { "literalString": "2026-10-28", "path": "xxx" }
      }
    },
    "action": {
      "name": "openLink",
      "args": {
        "literalString": { "url": "[https://www.example.com](https://www.example.com)" }
      }
    }
  }
}
```

- licenseNum: 必选，车牌号
  - literalString: 可选，车牌号字符串，如"粤B-88888"
  - path: 可选，车牌号对应的数据id
- leftDays: 必选，保险剩余天数
  - literalString: 可选，剩余天数数字，如30
  - path: 可选，剩余天数对应的数据id
- nextRenewalDate: 可选，下次可以续保的日期
  - literalString: 可选，日期字符串，格式如'2025-12-31'
  - path: 可选，续保日期对应的数据id
- policyInfo: 必选，保单信息
  - bizApply: 必选，商业险信息
    - invalidDate: 必选，商业险到期日
      - literalString: 可选，日期字符串，格式如'2025-12-31'
      - path: 可选，到期日对应的数据id
  - forceApply: 必选，交强险信息
    - invalidDate: 必选，交强险到期日
      - literalString: 可选，日期字符串，格式如'2025-12-31'
      - path: 可选，到期日对应的数据id
  - ppiInfo: 可选，驾乘险信息
    - invalidDate: 必选，驾乘险到期日
      - literalString: 可选，日期字符串，格式如'2025-12-31'
      - path: 可选，到期日对应的数据id
- action: 必选，交互操作
  - name: 必选，动作名称
    - openLink: 链接跳转
    - query: 发起用户问
  - args: 必选，操作参数
    - literalString: 可选，参数值
    - path: 可选，参数对应的数据id