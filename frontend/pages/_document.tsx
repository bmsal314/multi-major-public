import Document, {
  Html,
  Head,
  Main,
  NextScript,
  DocumentContext,
  DocumentInitialProps,
} from "next/document";
export default class MultiMajorDocument extends Document<
  DocumentInitialProps & { nonce: string }
> {
  static async getInitialProps(ctx: DocumentContext) {
    const props = await Document.getInitialProps(ctx);
    return { ...props, nonce: String(ctx.req?.headers["x-nonce"] ?? "") };
  }
  render() {
    return (
      <Html lang="en">
        <Head nonce={this.props.nonce} />
        <body>
          <a className="skip-link" href="#main-content">
            Skip to content
          </a>
          <div id="main-content">
            <Main />
          </div>
          <NextScript nonce={this.props.nonce} />
        </body>
      </Html>
    );
  }
}
