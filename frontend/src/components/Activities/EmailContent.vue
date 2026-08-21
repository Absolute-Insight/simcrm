<template>
  <!-- sandbox without allow-scripts: a srcdoc iframe is same-origin, so
       anything that ever slipped past the server-side sanitiser would have run
       with full access to this app's session. allow-same-origin stays because
       the onload handler below reads contentWindow.document to size the frame
       and mirror the theme; it grants no script execution on its own. -->
  <iframe
    ref="iframeRef"
    :srcdoc="htmlContent"
    sandbox="allow-same-origin"
    class="prose-f block h-10 max-h-[500px] w-full"
  />
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import emailContentStyles from './emailContent.css?inline'

const props = defineProps({
  content: { type: String, required: true },
})

const iframeRef = ref(null)
const _content = ref(props.content)

const parser = new DOMParser()
const doc = parser.parseFromString(_content.value, 'text/html')

const gmailReplyToContent = doc.querySelectorAll('div.gmail_quote')
const outlookReplyToContent = doc.querySelectorAll('div#appendonsend')
const replyToContent = doc.querySelectorAll('p.reply-to-content')

if (gmailReplyToContent.length) {
  _content.value = parseReplyToContent(doc, 'div.gmail_quote', true)
} else if (outlookReplyToContent.length) {
  _content.value = parseReplyToContent(doc, 'div#appendonsend')
} else if (replyToContent.length) {
  _content.value = parseReplyToContent(doc, 'p.reply-to-content')
}

function parseReplyToContent(doc, selector, forGmail = false) {
  function handleAllInstances(doc) {
    const replyToContentElements = doc.querySelectorAll(selector)
    if (replyToContentElements.length === 0) return
    const replyToContentElement = replyToContentElements[0]
    replaceReplyToContent(replyToContentElement, forGmail)
    handleAllInstances(doc)
  }

  handleAllInstances(doc)

  return doc.body.innerHTML
}

function replaceReplyToContent(replyToContentElement, forGmail) {
  if (!replyToContentElement) return
  let randomId = Math.random().toString(36).substring(2, 7)
  const wrapper = doc.createElement('div')
  wrapper.classList.add('replied-content')

  const collapseLabel = doc.createElement('label')
  collapseLabel.classList.add('collapse')
  collapseLabel.setAttribute('for', randomId)
  collapseLabel.innerHTML = '...'
  wrapper.appendChild(collapseLabel)

  const collapseInput = doc.createElement('input')
  collapseInput.setAttribute('id', randomId)
  collapseInput.setAttribute('class', 'replyCollapser')
  collapseInput.setAttribute('type', 'checkbox')
  wrapper.appendChild(collapseInput)

  if (forGmail) {
    const prevSibling = replyToContentElement.previousElementSibling
    if (prevSibling && prevSibling.tagName === 'BR') {
      prevSibling.remove()
    }
    let cloned = replyToContentElement.cloneNode(true)
    cloned.classList.remove('gmail_quote')
    wrapper.appendChild(cloned)
  } else {
    const allSiblings = Array.from(replyToContentElement.parentElement.children)
    const replyToContentIndex = allSiblings.indexOf(replyToContentElement)
    const followingSiblings = allSiblings.slice(replyToContentIndex + 1)

    if (followingSiblings.length === 0) return

    let clonedFollowingSiblings = followingSiblings.map((sibling) =>
      sibling.cloneNode(true),
    )

    const div = doc.createElement('div')
    div.append(...clonedFollowingSiblings)

    wrapper.append(div)

    // Remove all siblings after the reply-to-content element
    for (let i = replyToContentIndex + 1; i < allSiblings.length; i++) {
      replyToContentElement.parentElement.removeChild(allSiblings[i])
    }
  }

  replyToContentElement.parentElement.replaceChild(
    wrapper,
    replyToContentElement,
  )
}

// Defence in depth, not the primary control: frappe sanitises Text Editor
// fields with nh3 on save, and this is a second lock on the same door. 'none'
// by default blocks script, frame, object and form targets outright; images and
// fonts stay reachable because business email is full of logos and signatures,
// and inline styles are the sheet injected just below.
//
// Remote images do still load, which hands an external sender a read receipt on
// every rep who opens their mail. Blocking them is normal mail-client behaviour
// but needs a "load images" affordance to not look broken — tracked separately
// rather than smuggled in here.
const CSP = [
  "default-src 'none'",
  'img-src http: https: data: cid:',
  'font-src http: https: data:',
  "style-src 'unsafe-inline' http: https:",
].join('; ')

const htmlContent = `
<!DOCTYPE html>
<html>
<head>
  <meta http-equiv="Content-Security-Policy" content="${CSP}">
  <style>${emailContentStyles}</style>
</head>
<body>
    <div ref="emailContentRef" class="email-content prose-f">${_content.value}</div>
</body>
</html>
`

/* The frame's document is an island: it gets its own copy of the theme rather
   than inheriting one. Copying it once on load was not enough -- switching
   theme with mail on screen left every frame on the old value, so light-theme
   prose (near-black) sat on the dark app surface at 1.10:1 until a reload.
   Mirroring on every change is what keeps the two documents in step. */
let themeObserver = null

function mirrorTheme(frameHtml) {
  if (!frameHtml) return
  const theme = document.documentElement.getAttribute('data-theme')
  if (theme) frameHtml.setAttribute('data-theme', theme)
  else frameHtml.removeAttribute('data-theme')
}

watch(iframeRef, (iframe) => {
  themeObserver?.disconnect()
  themeObserver = null
  if (iframe) {
    iframe.onload = () => {
      const emailContent =
        iframe.contentWindow.document.querySelector('.email-content')
      let parent = emailContent.closest('html')

      mirrorTheme(parent)

      const resize = () => {
        iframe.style.height = parent.offsetHeight + 1 + 'px'
      }
      resize()

      /* `data-theme` is the attribute frappe-ui writes on <html>; watching the
         attribute rather than the composable keeps this working for every path
         that sets it -- the toggle, another tab, or the OS under 'system'. */
      themeObserver = new MutationObserver(() => {
        mirrorTheme(parent)
        /* A theme change can reflow the content (fonts, borders), so the frame
           has to be re-measured or it keeps a stale height. */
        resize()
      })
      themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme'],
      })

      let replyCollapsers = emailContent.querySelectorAll('.replyCollapser')
      if (replyCollapsers.length) {
        replyCollapsers.forEach((replyCollapser) => {
          replyCollapser.addEventListener('change', resize)
        })
      }
    }
  }
})

onBeforeUnmount(() => {
  themeObserver?.disconnect()
  themeObserver = null
})
</script>
