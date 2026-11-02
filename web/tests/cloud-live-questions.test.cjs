const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");

// Exercise the component's input handlers with a small deterministic hooks host.
test("single choice and custom input are exclusive and submit SDK option labels", async () => {
  const states = [];
  let cursor = 0;
  const react = {
    useEffect: () => {},
    useState(initial) {
      const index = cursor++;
      if (!(index in states)) states[index] = initial;
      return [states[index], value => { states[index] = typeof value === "function" ? value(states[index]) : value; }];
    },
  };
  const jsx = (type, props) => ({ type, props: props || {} });
  const Radio = Object.assign(function Radio() {}, { Group: "RadioGroup" });
  const Input = { TextArea: "TextArea" };
  const antd = { Alert: "Alert", Button: "Button", Checkbox: "Checkbox", Input, Radio,
    Space: "Space", Typography: { Title: "Title", Text: "Text", Paragraph: "Paragraph" } };
  const { LiveQuestions } = load("app/cloud-tasks/[taskId]/live-questions.tsx", { require: name => {
    if (name === "react") return react;
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx };
    if (name === "antd") return antd;
    if (name === "@/lib/i18n") return { useI18n: () => ({ t: (en) => en }) };
    return require(name);
  } });
  const submissions = [];
  const props = { request: { id: "request", status: "open", questions: [{ id: "q", question: "Choose",
    options: [{ label: "Visible label", value: "different-internal-value" }], multiple: false, allow_custom: true }] },
    onSubmit: async (...args) => submissions.push(args), onCancel: async () => {} };
  const render = () => { cursor = 0; return LiveQuestions(props); };
  const find = (tree, type) => {
    if (!tree || typeof tree !== "object") return undefined;
    if (tree.type === type) return tree;
    const children = tree.props?.children;
    for (const child of Array.isArray(children) ? children.flat(Infinity) : [children]) {
      const found = find(child, type);
      if (found) return found;
    }
  };
  let tree = render();
  assert.equal(find(tree, Radio).props.value, "Visible label");
  find(tree, "RadioGroup").props.onChange({ target: { value: "Visible label" } });
  tree = render();
  find(tree, "TextArea").props.onChange({ target: { value: "custom answer" } });
  tree = render();
  assert.equal(find(tree, "RadioGroup").props.value, undefined);
  find(tree, "RadioGroup").props.onChange({ target: { value: "Visible label" } });
  tree = render();
  assert.equal(find(tree, "TextArea").props.value, "");
  find(tree, "form").props.onSubmit({ preventDefault() {} });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(JSON.parse(JSON.stringify(submissions)), [["request", [{ id: "q", selected: ["Visible label"] }]]]);
});
