/* The rich-text editor, as a module of its own, so that it can be asked for
   on demand: `import()` of the whole experimental barrel would fetch
   everything in it. See components/Controls/LazyTextEditor.js. */
export { TextEditor as default } from 'frappe-ui/experimental'
