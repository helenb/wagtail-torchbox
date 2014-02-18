from datetime import date

from django.db import models
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.management import call_command
from django.dispatch import receiver
from django.shortcuts import render
from django.http import HttpResponse

from wagtail.wagtailcore.models import Page, Orderable
from wagtail.wagtailcore.fields import RichTextField
from wagtail.wagtailadmin.edit_handlers import FieldPanel, MultiFieldPanel, \
    InlinePanel, PageChooserPanel
from wagtail.wagtailimages.edit_handlers import ImageChooserPanel
from wagtail.wagtailimages.models import Image
from wagtail.wagtaildocs.edit_handlers import DocumentChooserPanel
from wagtail.wagtailsnippets.models import register_snippet

from modelcluster.fields import ParentalKey
from modelcluster.tags import ClusterTaggableManager
from taggit.models import Tag, TaggedItemBase
from south.signals import post_migrate

from torchbox.utils import export_event
    
COMMON_PANELS = (
    FieldPanel('slug'),
    FieldPanel('seo_title'),
    FieldPanel('show_in_menus'),
    FieldPanel('search_description'),
)

# A couple of abstract classes that contain commonly used fields

class LinkFields(models.Model):
    link_external = models.URLField("External link", blank=True)
    link_page = models.ForeignKey(
        'wagtailcore.Page',
        null=True,
        blank=True,
        related_name='+'
    )
    link_document = models.ForeignKey(
        'wagtaildocs.Document',
        null=True,
        blank=True,
        related_name='+'
    )

    @property
    def link(self):
        if self.link_page:
            return self.link_page.url
        elif self.link_document:
            return self.link_document.url
        else:
            return self.link_external

    panels = [
        FieldPanel('link_external'),
        PageChooserPanel('link_page'),
        DocumentChooserPanel('link_document'),
    ]

    class Meta:
        abstract = True


class ContactFields(models.Model):
    telephone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address_1 = models.CharField(max_length=255, blank=True)
    address_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=255, blank=True)
    post_code = models.CharField(max_length=10, blank=True)

    panels = [
        FieldPanel('telephone'),
        FieldPanel('email'),
        FieldPanel('address_1'),
        FieldPanel('address_2'),
        FieldPanel('city'),
        FieldPanel('country'),
        FieldPanel('post_code'),
    ]

    class Meta:
        abstract = True


# Carousel items

class CarouselItem(LinkFields):
    image = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+'
    )
    embed_url = models.URLField("Embed URL", blank=True)
    caption = models.CharField(max_length=255, blank=True)

    panels = [
        ImageChooserPanel('image'),
        FieldPanel('embed_url'),
        FieldPanel('caption'),
        MultiFieldPanel(LinkFields.panels, "Link"),
    ]

    class Meta:
        abstract = True


# Related links

class RelatedLink(LinkFields):
    title = models.CharField(max_length=255, help_text="Link title")

    panels = [
        FieldPanel('title'),
        MultiFieldPanel(LinkFields.panels, "Link"),
    ]

    class Meta:
        abstract = True


# Advert Snippet

class AdvertPlacement(models.Model):
    page = ParentalKey('wagtailcore.Page', related_name='advert_placements')
    advert = models.ForeignKey('torchbox.Advert', related_name='+')

class Advert(models.Model):
    page = models.ForeignKey(
        'wagtailcore.Page',
        related_name='adverts',
        null=True,
        blank=True
    )
    url = models.URLField(null=True, blank=True)
    text = models.CharField(max_length=255)

    panels = [
        PageChooserPanel('page'),
        FieldPanel('url'),
        FieldPanel('text'),
    ]

    def __unicode__(self):
        return self.text

register_snippet(Advert)


# Home Page

class HomePageCarouselItem(Orderable, CarouselItem):
    page = ParentalKey('torchbox.HomePage', related_name='carousel_items')

class HomePage(Page):
    search_name = "Homepage"

    class Meta:
        verbose_name = "Homepage"

HomePage.content_panels = [
    FieldPanel('title', classname="full title"),
    InlinePanel(HomePage, 'carousel_items', label="Carousel items"),
]

HomePage.promote_panels = [
    MultiFieldPanel(COMMON_PANELS, "Common page configuration"),
]


# Standard page

class StandardPageRelatedLink(Orderable, RelatedLink):
    page = ParentalKey('torchbox.StandardPage', related_name='related_links')

class StandardPage(Page):
    intro = RichTextField(blank=True)
    body = RichTextField(blank=True)
    feed_image = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+'
    )

    indexed_fields = ('intro', 'body', )
    search_name = None

StandardPage.content_panels = [
    FieldPanel('title', classname="full title"),
    FieldPanel('intro', classname="full"),
    FieldPanel('body', classname="full"),
    InlinePanel(StandardPage, 'related_links', label="Related links"),
]

StandardPage.promote_panels = [
    MultiFieldPanel(COMMON_PANELS, "Common page configuration"),
    ImageChooserPanel('feed_image'),
]


# Blog index page

class BlogIndexPageRelatedLink(Orderable, RelatedLink):
    page = ParentalKey('torchbox.BlogIndexPage', related_name='related_links')

class BlogIndexPage(Page):
    intro = RichTextField(blank=True)

    indexed_fields = ('intro', )
    search_name = "Blog"

    @property
    def blogs(self):
        # Get list of blog pages that are descendants of this page
        blogs = BlogPage.objects.filter(
            live=True,
            path__startswith=self.path
        )

        # Order by most recent date first
        blogs = blogs.order_by('-date')

        return blogs

    def serve(self, request):
        # Get blogs
        blogs = self.blogs

        # Filter by tag
        tag = request.GET.get('tag')
        if tag:
            blogs = blogs.filter(tags__name=tag)

        # Pagination
        page = request.GET.get('page')
        paginator = Paginator(blogs, 10)  # Show 10 blogs per page
        try:
            blogs = paginator.page(page)
        except PageNotAnInteger:
            blogs = paginator.page(1)
        except EmptyPage:
            blogs = paginator.page(paginator.num_pages)

        return render(request, self.template, {
            'self': self,
            'blogs': blogs,
        })

BlogIndexPage.content_panels = [
    FieldPanel('title', classname="full title"),
    FieldPanel('intro', classname="full"),
    InlinePanel(BlogIndexPage, 'related_links', label="Related links"),
]

BlogIndexPage.promote_panels = [
    MultiFieldPanel(COMMON_PANELS, "Common page configuration"),
]


# Blog page

class BlogPageRelatedLink(Orderable, RelatedLink):
    page = ParentalKey('torchbox.BlogPage', related_name='related_links')

class BlogPageTag(TaggedItemBase):
    content_object = ParentalKey('torchbox.BlogPage', related_name='tagged_items')

class BlogPageAuthor(Orderable):
    page = ParentalKey('torchbox.BlogPage', related_name='related_author')
    author = models.ForeignKey(
        'torchbox.PersonPage',
        null=True,
        blank=True,
        related_name='+'
    )

class BlogPage(Page):
    intro = RichTextField(blank=True)
    body = RichTextField()
    tags = ClusterTaggableManager(through=BlogPageTag, blank=True)
    date = models.DateField("Post date")
    feed_image = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+'
    )

    indexed_fields = ('body', )
    search_name = "Blog Entry"

    @property
    def blog_index(self):
        # Find blog index in ancestors
        for ancestor in reversed(self.get_ancestors()):
            if isinstance(ancestor.specific, BlogIndexPage):
                return ancestor

        # No ancestors are blog indexes,
        # just return first blog index in database
        return BlogIndexPage.objects.first()

BlogPage.content_panels = [
    FieldPanel('title', classname="full title"),
    InlinePanel(BlogPage, 'related_author', label="Author"),
    FieldPanel('date'),
    FieldPanel('intro', classname="full"),
    FieldPanel('body', classname="full"),
    InlinePanel(BlogPage, 'related_links', label="Related links"),
]

BlogPage.promote_panels = [
    MultiFieldPanel(COMMON_PANELS, "Common page configuration"),
    ImageChooserPanel('feed_image'),
    FieldPanel('tags'),
]


# Job page

class JobPage(Page):
    body = RichTextField()

    indexed_fields = ('body', )

JobPage.content_panels = [
    FieldPanel('title', classname="full title"),
    FieldPanel('body', classname="full"),
]

JobPage.promote_panels = [
    MultiFieldPanel(COMMON_PANELS, "Common page configuration"),
]

# Jobs index page

class JobIndexPage(Page):
    intro = RichTextField(blank=True)

    indexed_fields = ('intro', )
    # TODO: what is this? 
    # search_name = "Job"

    @property
    def jobs(self):
        # Get list of blog pages that are descendants of this page
        jobs = JobPage.objects.filter(
            live=True,
            path__startswith=self.path
        )

        # Order by most recent date first
        #jobs = jobs.order_by('-date')

        return jobs

    def serve(self, request):
        # Get jobs
        jobs = self.jobs

        # Pagination
        page = request.GET.get('page')
        paginator = Paginator(jobs, 10)  # Show 10 jobs per page
        try:
            jobs = paginator.page(page)
        except PageNotAnInteger:
            jobs = paginator.page(1)
        except EmptyPage:
            jobs = paginator.page(paginator.num_pages)

        return render(request, self.template, {
            'self': self,
            'jobs': jobs,
        })


JobIndexPage.content_panels = [
    FieldPanel('title', classname="full title"),
    FieldPanel('intro', classname="full"),
]

JobIndexPage.promote_panels = [
    MultiFieldPanel(COMMON_PANELS, "Common page configuration"),
]



# Work page

class WorkPageScreenshot(Orderable):
    page = ParentalKey('torchbox.WorkPage', related_name='screenshots')
    image = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+'
    )

    panels = [
        ImageChooserPanel('image'),
    ]


# class WorkPageRelatedLink(Orderable, RelatedLink):
#     page = ParentalKey('torchbox.WorkPage', related_name='related_links')

class WorkPage(Page):
    summary = models.CharField(max_length=255)
    intro = RichTextField(blank=True)
    body = RichTextField(blank=True)

WorkPage.content_panels = [
    FieldPanel('title', classname="full title"),
    FieldPanel('summary'),
    FieldPanel('intro', classname="full"),
    FieldPanel('body', classname="full"),
    InlinePanel(WorkPage, 'screenshots', label="Screenshots"),
    # InlinePanel(WorkPage, 'related_links', label="Related links"),
]

WorkPage.promote_panels = [
    MultiFieldPanel(COMMON_PANELS, "Common page configuration"),
]


# Work index page

class WorkIndexPage(Page):
    intro = RichTextField(blank=True)

    @property
    def work(self):
        # Get list of person pages that are descendants of this page
        work = WorkPage.objects.filter(
            live=True,
            path__startswith=self.path
        )

        # Order by most recent date first
        #people = people.order_by('-date')

        return work

    def serve(self, request):
        # Get people
        work = self.work

        # Pagination
        page = request.GET.get('page')
        paginator = Paginator(work, 10)  # Show 10 jobs per page
        try:
            work = paginator.page(page)
        except PageNotAnInteger:
            work = paginator.page(1)
        except EmptyPage:
            work = paginator.page(paginator.num_pages)

        return render(request, self.template, {
            'self': self,
            'work': work,
        })


WorkIndexPage.content_panels = [
    FieldPanel('title', classname="full title"),
    FieldPanel('intro', classname="full"),
]

WorkIndexPage.promote_panels = [
    MultiFieldPanel(COMMON_PANELS, "Common page configuration"),
]


# Person page

class PersonPageRelatedLink(Orderable, RelatedLink):
    page = ParentalKey('torchbox.PersonPage', related_name='related_links')

class PersonPage(Page, ContactFields):
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    role = models.CharField(max_length=255, blank=True)
    intro = RichTextField(blank=True)
    biography = RichTextField(blank=True)
    image = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+'
    )
    feed_image = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+'
    )

    indexed_fields = ('first_name', 'last_name', 'intro', 'biography')
    search_name = "Person"

PersonPage.content_panels = [
    FieldPanel('title', classname="full title"),
    FieldPanel('first_name'),
    FieldPanel('last_name'),
    FieldPanel('intro', classname="full"),
    FieldPanel('biography', classname="full"),
    ImageChooserPanel('image'),
    MultiFieldPanel(ContactFields.panels, "Contact"),
    InlinePanel(PersonPage, 'related_links', label="Related links"),
]

PersonPage.promote_panels = [
    MultiFieldPanel(COMMON_PANELS, "Common page configuration"),
    ImageChooserPanel('feed_image'),
]



# Person index

class PersonIndexPage(Page):
    intro = RichTextField(blank=True)

    indexed_fields = ('intro', )
    # TODO: what is this? 
    # search_name = "Job"

    @property
    def people(self):
        # Get list of person pages that are descendants of this page
        people = PersonPage.objects.filter(
            live=True,
            path__startswith=self.path
        )

        # Order by most recent date first
        #people = people.order_by('-date')

        return people

    def serve(self, request):
        # Get people
        people = self.people

        # Pagination
        page = request.GET.get('page')
        paginator = Paginator(people, 10)  # Show 10 jobs per page
        try:
            people = paginator.page(page)
        except PageNotAnInteger:
            people = paginator.page(1)
        except EmptyPage:
            people = paginator.page(paginator.num_pages)

        return render(request, self.template, {
            'self': self,
            'people': people,
        })


PersonIndexPage.content_panels = [
    FieldPanel('title', classname="full title"),
    FieldPanel('intro', classname="full"),
]

PersonIndexPage.promote_panels = [
    MultiFieldPanel(COMMON_PANELS, "Common page configuration"),
]
