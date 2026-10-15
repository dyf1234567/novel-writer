#!/usr/bin/env node
'use strict';

// 正文里的非叙述片段。标点整理与 AI 句式检测都要认这些区间：前者不能把结构里的横线当成
// 停顿标点改写（改死表格、改死链接），后者不能把链接里的 `--` 报成破折号要求作者删掉。
// 两边共用同一份定义，否则一个放行、一个报错，含链接的章节会永远过不了收口闸。

const URL_PATTERN = /(?:https?:|ftp:)\/\/[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]+|www\.[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]+/gi;

// 返回 [start, end) 区间数组。末尾的英文标点不算地址的一部分。
function urlSpans(line) {
  const spans = [];
  let match;
  URL_PATTERN.lastIndex = 0;
  while ((match = URL_PATTERN.exec(line)) !== null) {
    let end = match.index + match[0].length;
    while (end > match.index && ',.;:?!)'.includes(line[end - 1])) end -= 1;
    spans.push([match.index, end]);
  }
  return spans;
}

function insideSpans(start, end, spans) {
  return spans.some(([spanStart, spanEnd]) => start < spanEnd && end > spanStart);
}

module.exports = { urlSpans, insideSpans };
