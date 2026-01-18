from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    # Create mobile viewport
    context = browser.new_context(
        viewport={'width': 375, 'height': 667},
        user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15'
    )
    page = context.new_page()

    page.goto('http://localhost:4323/')
    page.wait_for_load_state('networkidle')

    # Take screenshot of mobile header
    page.screenshot(path='C:/Users/jef_p/toronto-airbnb-management/mobile_header.png')

    # Find the phone link
    phone_link = page.locator('.mobile-phone-link')

    # Check if it exists and is visible
    print(f"Phone link count: {phone_link.count()}")
    print(f"Phone link visible: {phone_link.is_visible()}")

    # Get the href attribute
    href = phone_link.get_attribute('href')
    print(f"Phone link href: {href}")

    # Get bounding box to see position
    box = phone_link.bounding_box()
    print(f"Bounding box: {box}")

    # Check what element is at the phone link's position
    if box:
        center_x = box['x'] + box['width'] / 2
        center_y = box['y'] + box['height'] / 2
        element_at_point = page.evaluate(f'''() => {{
            const el = document.elementFromPoint({center_x}, {center_y});
            return el ? {{
                tagName: el.tagName,
                className: el.className,
                id: el.id,
                href: el.href || null
            }} : null;
        }}''')
        print(f"Element at phone link center: {element_at_point}")

    # Get computed styles
    styles = page.evaluate('''() => {
        const el = document.querySelector('.mobile-phone-link');
        const computed = window.getComputedStyle(el);
        return {
            display: computed.display,
            visibility: computed.visibility,
            pointerEvents: computed.pointerEvents,
            zIndex: computed.zIndex,
            position: computed.position
        };
    }''')
    print(f"Computed styles: {styles}")

    browser.close()
